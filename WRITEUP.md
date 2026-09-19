# DA3408 Assignment2

**Name:** K.Rishitha   ,  **Roll no:** DA24B040 

---

## Q1 : Single-stage vs. multi-stage Docker

| Image | Dockerfile | Size |
|---|---|---|
| `spam-api:naive` | `app/Dockerfile.naive` (single stage) | 1.47GB |
| `spam-api:v1` | `app/Dockerfile` (multi-stage) | 502 MB |
| **Reduction** | | **70.3 %** |

Both images serve `GET /healthz` and `POST /predict` the same way, I tested this by curling both containers with the same spam/ham messages and got identical labels. That check is saved in `evidence/q1_sizes.txt`.

**Why the multi-stage image is smaller.** I used `python:3.11-slim` as the base for both Dockerfiles, so the size gap isn't coming from the base image at all, it's entirely from what each Dockerfile installs and leaves behind.

I confirmed this by shelling into both images and checking directly (also in `evidence/q1_sizes.txt`):

- `naive` has `gcc` sitting at `/usr/bin/gcc`; `v1` has no compiler at all. I install `build-essential`/`gcc`/`g++` in my builder stage in case scikit-learn/scipy need to compile anything, but nothing in the runtime `requirements.txt` needs a compiler, so it never makes it into the final image.
- `naive` has pandas fully installed (`/usr/local/lib/python3.11/site-packages/pandas`). That's actually pointless in the final image ,`main.py` only calls `joblib.load()` and `.predict()`, pandas is only used by `train.py` to read the csv. Because I split `requirements-train.txt` from `requirements.txt`, the runtime venv in `v1` never installs pandas at all.
- `naive` still has `spam_dataset.csv` (61 KB) and `train.py` sitting in `/app`, along with a 92 MB pip cache that never got cleaned up. None of that exists in `v1`, training happens in the builder stage and only the ~40 KB `model.joblib` crosses over to the runtime stage.

So really it comes down to: the naive build does everything in one place and keeps everything it touched, while the multi-stage build throws away the builder stage and only copies out the finished venv plus the trained model.


---
## Q2: Docker Compose + Redis cache

`docker-compose.yml` has two services :`api` (built off the multi-stage Dockerfile) and `cache` (`redis:7-alpine`). Compose puts both on the same project network and gives each service name its own DNS entry, so `main.py` just points `REDIS_HOST` at `cache` and it resolves without me hardcoding any IP. I checked this directly:

```bash
docker compose exec api python -c "import socket; print(socket.gethostbyname('cache'))"
```

which returned `172.19.0.2`, confirming Compose's embedded DNS is resolving the service name to the actual container IP on its own. `docker compose exec cache redis-cli ping` also returned `PONG`, so both containers were reachable over the project network.

I also used `depends_on` with `condition: service_healthy` so the API container doesn't even start until Redis actually responds to a `PING`, not just once the container exists, but once it's actually ready to serve. The logs confirm this on startup:
```
[startup] cache enabled -> cache:6379 ttl=300s
[startup] model loaded from /app/model.joblib; version=1.0.0
```

For the caching logic itself, `main.py` hashes the incoming text and checks Redis first before doing anything else. On a miss it runs the model, then `SETEX`s the result with a 300s TTL. On a hit it skips the model entirely and returns the cached label straight away. I kept the response body exactly `{"label": ...}` like the assignment asks, I didn't want to change the API contract just to expose caching info, so instead I put that in headers (`X-Cache`, `X-Elapsed-Ms`) which don't affect the body at all. A quick manual check on the same message showed this clearly:

- First request: `x-cache: MISS`, `x-elapsed-ms: 17.553`
- Same request again: `x-cache: HIT`, `x-elapsed-ms: 0.853`

**Evidence.** One before/after curl like the above is a nice sanity check but isn't real evidence on its own, a single sample can be thrown off by things like the very first Redis connection warming up. So `scripts/bench_cache.py` sends 200 unique messages (each one guaranteed to be a fresh miss), then replays the exact same 200 messages (each one now guaranteed to be a hit), and compares the two sets properly:

| Population | mean | p50 | p95 |
|---|---|---|---|
| MISS (model runs) | 1.789 ms | 1.649 ms | 2.409 ms |
| HIT (Redis only) | 0.651 ms | 0.538 ms | 1.243 ms |
| **Speedup** | **2.75×** | **3.07×** | |

All 200 labels matched exactly between the two runs, so the cache is only changing how fast the answer comes back, not what the answer actually is. Redis's own `/cache/stats` endpoint backed this up too,  `{"cache":"enabled","keyspace_hits":201,"keyspace_misses":206,"keys":206}`, full output is in `evidence/q2_bench.txt`.

**Compose vs Kubernetes.** A single Dockerfile can only describe one image and one container in isolation, it has no way to say "this container needs to talk to that other container by name" or "start this one only after that one is healthy." That's the gap Compose fills: it wires multiple containers together on one machine. But that's also its ceiling, Compose only ever knows about one Docker host, it has no concept of multiple machines at all. Kubernetes is built for the opposite problem: it schedules pods across a whole cluster of nodes, and it comes with control loops Compose just doesn't have, restarting things on a different node if one dies, rolling out a new version without downtime, and giving you a stable Service address in front of pods that come and go. Basically, Compose answers "how do these containers talk to each other on my one machine," and Kubernetes answers "how does this whole app keep running correctly across many machines."

---
## Q3: Kubernetes Indexed Job, parallel shard validation

Parallelism 4, completions 8, CPU requests and limits both set to 500m.

The validator itself is plain single threaded Python, just csv.DictReader plus one regex check per row, so it physically cannot use more than one core no matter how much I give it, and in practice it finishes a 250 row shard in well under a tenth of a second (my logs show elapsed_seconds between 0.0006 and 0.04 per shard). 500m is more than enough and the pod is never throttled. I set requests equal to limits on purpose too, since that puts each pod in the Guaranteed QoS class, which is what makes the scheduling math below something I can actually trust rather than a guess.

The assignment assumes a cluster of 2 nodes with 2 allocatable CPUs each, 4 total nominal. Real allocatable is always a bit lower than nominal since kubelet and the kube system pods (kube proxy, CoreDNS, the storage provisioner) need some of that themselves, so I worked with roughly 1750m usable per node as a reasonable estimate. The part that actually decides the parallelism number is that scheduling happens per node, not across the whole cluster at once. A pod only starts if one specific node has 500m free right now. That gives 3 pods per node under this assumption, 6 schedulable total. I picked 4, two pods per node, 2000m total, so all four start together with nothing left Pending and kube system still has headroom. With completions set to 8, that runs as two clean waves of four, which matches exactly what I saw.

I didn't pick 8 because 8 times 500m is 4000m, the entire nominal capacity of the assumed cluster and more than what's actually usable once system pods are accounted for. Some pods would sit Pending until earlier ones finished, so the manifest would allow 8 on paper but never actually reach 8 running at once, and this question specifically asks for evidence the chosen number was really hit.

restartPolicy is set to Never rather than OnFailure, since OnFailure restarts the same container in place and you'd need the previous flag to see an earlier attempt's logs, while Never gives every attempt a fresh pod with its own log that's easy to grab later. The manifest also pulls metadata.name into POD_NAME and spec.nodeName into NODE_NAME through the Downward API, on top of JOB_COMPLETION_INDEX which Kubernetes sets automatically for an Indexed Job.

For the concurrency evidence, kubectl get pods l app=shard validation o wide showed all 4 pods Running at the same time, two on minikube and two on minikube m02:
```text
shard-validation-0-bt4x8   1/1   Running   minikube-m02
shard-validation-1-bnfx4   1/1   Running   minikube-m02
shard-validation-2-gcw6m   1/1   Running   minikube
shard-validation-3-czqz6   1/1   Running   minikube
```

The Job then finished all 8 completions in 56 seconds total, which fits two waves of four running one after another.

On why I collected results through the Kubernetes API instead of a shared volume, minikube's default standard StorageClass is backed by hostPath, so a PVC just becomes a folder on one specific node's disk. That's ReadWriteOnce and tied to that one node, and there's no ReadWriteMany provisioner set up by default. Since my four concurrent pods land across both nodes, half of them couldn't even mount a volume sitting on the other node, and forcing everything onto a single node just to make a shared folder work would remove the parallelism entirely. kubectl logs avoids all of this since it's an API server call that gets proxied to whichever kubelet the pod actually ran on, no storage class involved at all. So each pod prints one RESULT_JSON line and I pull them out per shard using the batch.kubernetes.io/job completion index label.

The results I collected:

| Shard | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | Total |
|---|---|---|---|---|---|---|---|---|---|
| Invalid rows | 2 | 19 | 28 | 33 | 38 | 38 | 57 | 45 | 260 |
| out of 250 rows | 0.8% | 7.6% | 11.2% | 13.2% | 15.2% | 15.2% | 22.8% | 18.0% | 13.0% |

These match GROUND_TRUTH.txt exactly, shard by shard, which I checked by running a throwaway pod off the same image and catting the file directly (0,2 / 1,19 / 2,28 / 3,33 / 4,38 / 5,38 / 6,57 / 7,45). Since the shard generator is seeded, that ground truth file already knew the right answer before the Job ever ran.

If the cluster instead had 3 nodes at 2 CPU each, 6 total, I would raise parallelism to 8. Usable allocatable under the same assumption goes up to roughly 1.5 times what it was, so each node can now fit 3 pods at 500m, giving 9 schedulable slots against only 8 shards. All eight would run in a single wave instead of two, cutting the total runtime by close to half, and there'd still be room left for system pods. There's no reason to push parallelism any higher than 8 either way, since there are only 8 shards to validate in the first place.

---
## Q4: Deployment, self healing and rolling updates

The Deployment runs 2 replicas with requests of 250m CPU and 512Mi memory, limits of 500m and 512Mi, a readinessProbe hitting /healthz, and a rolling update strategy with maxUnavailable set to 0 and maxSurge set to 1. The Service is a NodePort selecting app=spam-api.

For self healing, I deleted one running pod directly with kubectl delete pod. Right before deleting it I confirmed both pods were owned by the same ReplicaSet, not the Deployment itself:

```text
spam-api-865d7f44b5-wp8wh <- owned by ReplicaSet/spam-api-865d7f44b5
spam-api-865d7f44b5-wrfsn <- owned by ReplicaSet/spam-api-865d7f44b5
```

After deleting spam-api-865d7f44b5-wp8wh, the very next get pods call showed a new pod, spam-api-865d7f44b5-jpbmd, already scheduled on minikube-m02 and starting up while the surviving pod kept serving. The events confirmed the sequence directly:

```text
4s   Normal   Killing      pod/spam-api-865d7f44b5-wp8wh   Stopping container api
4s   Normal   Scheduled    pod/spam-api-865d7f44b5-jpbmd   Successfully assigned default/spam-api-865d7f44b5-jpbmd to minikube-m02
2s   Normal   Started      pod/spam-api-865d7f44b5-jpbmd   Container started
2s   Normal   Created      pod/spam-api-865d7f44b5-jpbmd   Container created
2s   Normal   Pulled       pod/spam-api-865d7f44b5-jpbmd   Container image "spam-api:v1" already present on machine and can be accessed by the pod
```

Once jpbmd passed its readiness check, the Deployment was back to 2/2 with jpbmd replacing wp8wh, a different name and a fresh age, and the old pod completely gone. The controller responsible for this is the ReplicaSet controller, not the Deployment controller directly. The Deployment only manages ReplicaSets, and each ReplicaSet in turn manages pods, which is exactly what the ownerReferences output above shows. It decides a replacement is needed just by running a constant reconciliation loop, it counts how many pods currently match its label selector, compares that number against its desired replica count, and if there's a shortfall it creates however many pods are missing. There's no special delete event it's reacting to, it simply notices 1 does not equal 2 and corrects it.

For the rolling update, spam-api:v2 is built from the exact same Dockerfile, only difference is the build arg APP_VERSION set to 2.0.0, so /healthz on the new image is expected to report version 2.0.0 instead of 1.0.0. I triggered the update with kubectl set image on the deployment, followed by kubectl set env to update the version label and an annotate call to record a change cause. kubectl rollout status showed the update progressing in stages, first 1 out of 2 replicas updated while the new pod came up, then 1 old replica pending termination while Kubernetes waited for the new pod's readiness probe to pass before killing the old one, and it finished with deployment successfully rolled out. This staged sequence is itself the evidence for maxUnavailable set to 0, at no point did the rollout status output show fewer than 2 replicas available, it only ever showed one being added before one was removed.

kubectl get rs afterward showed the new ReplicaSet, spam-api-749cf67dd7, sitting at 2/2/2 while the two earlier ReplicaSets were scaled down to zero:

```text
NAME                  DESIRED   CURRENT   READY   AGE
spam-api-6ddfb6b7fb   0         0         0       23s
spam-api-749cf67dd7   2         2         2       23s
spam-api-865d7f44b5   0         0         0       4m28s
```

rollout history listed the update as revision 3 with the change cause I set. I also ran kubectl rollout undo afterward as an extra check, and history correctly picked up a fourth revision recreating the earlier spec, confirming rollback works the same way a forward rollout does.

With maxUnavailable set to 0, Kubernetes is required to bring a new pod all the way up and pass its readinessProbe before it's allowed to kill an old one, which is what keeps at least 2 ready pods behind the Service at every point during the update, and the staged rollout status output above shows exactly that behaviour happening in practice.

If this had been a Job instead of a Deployment, none of this rollout machinery would exist at all. A Job's pod template is effectively fixed once it's created, so kubectl set image wouldn't behave the same way, there would be no second ReplicaSet, no rollout status, no rollout history, and no rollback. Shipping a new version would mean deleting the whole Job and creating a new one, and since Job pods are meant to run to completion and exit rather than serve continuously, there would be an actual gap where the API isn't available at all. A Service also doesn't make much sense sitting in front of a Job, since its pods keep completing and disappearing rather than staying up to serve traffic.

More generally, a Deployment fits a workload that's supposed to always be running and answering requests, so its whole design is built around keeping N replicas alive and swapping in new versions without any downtime. A Job fits the opposite kind of workload, one that's supposed to finish, so it tracks successful completions and simply stops once it hits the target, a completed shard validator pod is a success, not something that needs restarting. Using a Deployment for the Q3 batch job would mean Kubernetes endlessly recreating pods that were actually done, and using a Job for this API would mean nothing brings a crashed pod back. Each one is built around exactly the condition its own workload cares about, and that's the actual reason one is the right fit for serving and the other for batch work.



