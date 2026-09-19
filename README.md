# DA3408: Module 3 Assignment

Spam-detection API (TF-IDF + MultinomialNB, FastAPI) packaged with Docker,
orchestrated with Docker Compose, and run on Kubernetes.

```
.
├── app/
│   ├── main.py                  # FastAPI service: POST /predict, GET /healthz
│   ├── train.py                 # TF-IDF + MultinomialNB -> model.joblib
│   ├── generate_dataset.py      # seeded 1000-row spam_dataset.csv
│   ├── requirements-train.txt   # BUILD-ONLY deps (pandas lives here)
│   ├── requirements.txt         # RUNTIME deps (no pandas, no build tools)
│   ├── Dockerfile.naive         # Q1.1 single-stage baseline
│   ├── Dockerfile               # Q1.2 multi-stage (also used by Q2 and Q4)
│   └── .dockerignore
├── docker-compose.yml           # Q2: api + redis:7-alpine
├── q3-shard-validator/
│   ├── generate_shards.py       # seeded 8 shards + GROUND_TRUTH.txt
│   ├── validate_shard.py        # validates shard $JOB_COMPLETION_INDEX
│   └── Dockerfile
├── k8s/
│   ├── q3-indexed-job.yaml      # Q3 Indexed Job (completions 8, parallelism 4)
│   ├── q4-deployment.yaml       # Q4 Deployment (2 replicas, readinessProbe)
│   └── q4-service.yaml          # Q4 NodePort Service
├── scripts/
│   ├── q1_sizes.sh              # builds both images, reports sizes + % reduction
│   ├── bench_cache.py           # Q2 miss-vs-hit latency benchmark
│   ├── q3_collect.sh            # Q3 concurrency snapshot + log-based collection
│   ├── q4_selfheal.sh           # Q4 delete-a-pod evidence
│   └── q4_rollout.sh            # Q4 rolling update + zero-downtime probe
├── evidence/                    # all captured command output lands here
└── WRITEUP.md
|__ Image evidences              # contains image evidences
|__ MANUAL_COMMANDS.md           # The commands I ran
|__ AIOps_Report2                # The pdf report                    

```

Prerequisites: Docker Engine + `docker compose` v2, `minikube`, `kubectl`,
Python 3 on the host (only for `bench_cache.py`). Everything is CPU-only.

```bash
chmod +x scripts/*.sh
```

---

## Q1: Single-stage vs. multi-stage

One command builds both, reports sizes and the percentage reduction, dumps what
is actually inside each image, and checks both serve identically:

```bash
./scripts/q1_sizes.sh
```

Or manually:

```bash
docker build -f app/Dockerfile.naive -t spam-api:naive ./app
docker build -f app/Dockerfile       -t spam-api:v1 --build-arg APP_VERSION=1.0.0 ./app
docker images | grep spam-api

docker run -d --name api -p 8000:8000 spam-api:v1
curl localhost:8000/healthz
curl -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"WIN a FREE iPhone now! Click here: bit.ly/xyz123"}'
# -> {"label":"spam"}
curl -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"Hey, are we still meeting for lunch on Friday?"}'
# -> {"label":"ham"}
docker rm -f api
```

---

## Q2: Docker Compose + Redis cache

```bash
docker compose up --build -d
docker compose ps
docker compose logs api | head -20        # should show "cache enabled -> cache:6379"
```

Service-name DNS proof (the API resolves the hostname `cache`, never an IP):

```bash
docker compose exec api python -c "import socket; print(socket.gethostbyname('cache'))"
docker compose exec cache redis-cli ping
```

Cache-hit speedup evidence:

```bash
python3 scripts/bench_cache.py --n 200 | tee evidence/q2_bench.txt
```

It sends 200 unique messages (all MISS), replays the same 200 (all HIT), asserts
the labels are identical, and prints mean/p50/p95 for each population plus the
speedup factor. A single curl pair is not usable evidence at these latencies —
that's why this is a 200-sample comparison.

Quick manual sanity check of the headers:

```bash
curl -si -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"Congratulations! You have WON a laptop. Claim NOW at tinyurl.com/abc"}' \
  | grep -iE 'x-cache|x-elapsed'    # MISS
# repeat the same command -> HIT, with a smaller X-Elapsed-Ms
```

Tear down: `docker compose down -v`

---

## Q3: Kubernetes Indexed Job

Start the 2-node / 2-CPU-per-node cluster the question specifies:

```bash
minikube delete
minikube start --nodes 2 --cpus 2 --memory 3g --driver=docker
kubectl get nodes -o wide
kubectl describe nodes | grep -A6 'Allocatable'   # record real allocatable CPU
```

Build the validator image and load it onto **both** nodes:

```bash
docker build -t spam-shard-validator:v1 ./q3-shard-validator
minikube image load spam-shard-validator:v1
```

Run the Job and collect evidence:

```bash
kubectl apply -f k8s/q3-indexed-job.yaml
./scripts/q3_collect.sh
```

`q3_collect.sh` polls `kubectl get pods -o wide` every 2 s and saves the snapshot
with the highest simultaneous Running count to `evidence/q3_pods_wide.txt` —
that's the proof parallelism 4 was *reached*, not merely permitted. It then reads
each shard's result through the Kubernetes API:

```bash
kubectl logs -l batch.kubernetes.io/job-completion-index=3 --tail=-1
```

Ground truth to check the counts against is baked into the image at
`/data/GROUND_TRUTH.txt` (the script prints it at the end).

Watch it live in a second terminal if you want a screenshot:

```bash
watch -n1 kubectl get pods -l app=shard-validation -o wide
```

Clean up: `kubectl delete -f k8s/q3-indexed-job.yaml`

---

## Q4: Deployment: self-healing and rolling update

Build v1 and v2 (identical except the version string `/healthz` returns), load
both into minikube, and deploy:

```bash
docker build -f app/Dockerfile -t spam-api:v1 --build-arg APP_VERSION=1.0.0 ./app
docker build -f app/Dockerfile -t spam-api:v2 --build-arg APP_VERSION=2.0.0 ./app
minikube image load spam-api:v1
minikube image load spam-api:v2

kubectl apply -f k8s/q4-deployment.yaml -f k8s/q4-service.yaml
kubectl rollout status deployment/spam-api
kubectl get pods -l app=spam-api -o wide

URL=$(minikube service spam-api --url | head -1)
curl -s $URL/healthz                        # {"status":"ok","version":"1.0.0",...}
curl -s -X POST $URL/predict -H 'Content-Type: application/json' \
  -d '{"text":"URGENT: Your account will be suspended. Verify at win-now.co/claim"}'
```

**Self-healing (part 2):**

```bash
./scripts/q4_selfheal.sh
```

Deletes one pod, shows the replacement appearing, and prints each pod's
`ownerReferences` so the write-up can name the ReplicaSet concretely.

**Rolling update (part 3):**

```bash
./scripts/q4_rollout.sh
```

Runs a 10-req/s probe against the Service for the whole rollout and counts
non-200 responses (expected: 0), while capturing `kubectl rollout status` and
`kubectl rollout history`. With `maxUnavailable: 0` + `maxSurge: 1` and a
readinessProbe on `/healthz`, at least 2 Ready pods exist at every instant.

Roll back if you want a second history entry:

```bash
kubectl rollout undo deployment/spam-api
kubectl rollout history deployment/spam-api
```

Clean up: `kubectl delete -f k8s/q4-deployment.yaml -f k8s/q4-service.yaml`

---

## Submission checklist

- [ ] `evidence/q1_sizes.txt` — both sizes + % reduction
- [ ] `evidence/q2_bench.txt` — miss vs hit latencies, speedup factor
- [ ] `evidence/q3_pods_wide.txt` — 4 pods Running concurrently, `-o wide`
- [ ] `evidence/q3_results.txt` — per-shard invalid counts vs ground truth
- [ ] `evidence/q4_selfheal.txt` — pod deleted and recreated
- [ ] `evidence/q4_rollout.txt` + `evidence/q4_downtime_probe.txt`
- [ ] `WRITEUP.md` 

