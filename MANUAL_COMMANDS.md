# Commands I used in my terminal.

---

## Q1: Single-stage vs. multi-stage Docker

```bash
cd aiops-mod3

# Build the naive single-stage image
docker build -f app/Dockerfile.naive -t spam-api:naive ./app

# Build the multi-stage image
docker build -f app/Dockerfile -t spam-api:v1 --build-arg APP_VERSION=1.0.0 ./app

# Report sizes
docker images | grep -E "REPOSITORY|spam-api"

# Compute % reduction (paste the two sizes you see above)
docker image inspect spam-api:naive --format '{{.Size}}'
docker image inspect spam-api:v1    --format '{{.Size}}'

# Prove both images behave identically
docker run -d --name test-naive -p 8000:8000 spam-api:naive
sleep 3
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"WIN a FREE iPhone now! Click here: bit.ly/xyz123"}'
docker rm -f test-naive

docker run -d --name test-multi -p 8000:8000 spam-api:v1
sleep 3
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"WIN a FREE iPhone now! Click here: bit.ly/xyz123"}'
docker rm -f test-multi

# What got left behind in the builder stage (evidence for the explanation)
docker run --rm --entrypoint sh spam-api:naive -c "command -v gcc; python -c 'import pandas; print(pandas.__file__)'"
docker run --rm --entrypoint sh spam-api:v1     -c "command -v gcc; python -c 'import pandas; print(pandas.__file__)'" || echo "pandas not installed -- expected"
```

---

## Q2: Docker Compose + Redis cache

```bash
# Bring up the two-service stack
docker compose up --build -d
docker compose ps

# Show the API found Redis at startup
docker compose logs api | head -20

# Prove service-name DNS resolution (not a hardcoded IP)
docker compose exec api python -c "import socket; print(socket.gethostbyname('cache'))"
docker compose exec cache redis-cli ping

# Manual miss-then-hit proof (headers show X-Cache and X-Elapsed-Ms)
curl -si -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"Congratulations! You have WON a laptop. Claim NOW at tinyurl.com/abc"}' \
  | grep -iE 'x-cache|x-elapsed'
curl -si -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"text":"Congratulations! You have WON a laptop. Claim NOW at tinyurl.com/abc"}' \
  | grep -iE 'x-cache|x-elapsed'

# Full 200-vs-200 benchmark (the actual rubric evidence)
python3 scripts/bench_cache.py --n 200 | tee evidence/q2_bench.txt

# Redis-side confirmation
curl -s localhost:8000/cache/stats

# Tear down
docker compose down -v
```

---

## Q3: Kubernetes Indexed Job

```bash
# Fresh 2-node, 2-CPU-per-node cluster (matches the assignment's constraint)
minikube delete
minikube start --nodes 2 --cpus 2 --memory 3g --driver=docker
kubectl get nodes -o wide
kubectl describe nodes | grep -A6 Allocatable

# Build and load the validator image onto both nodes
docker build -t spam-shard-validator:v1 ./q3-shard-validator
minikube image load spam-shard-validator:v1

# Apply the Indexed Job
kubectl apply -f k8s/q3-indexed-job.yaml

# Watch pods come up — run this in a SECOND terminal while the Job runs,
# or just repeat it manually every couple seconds to catch 4 pods Running
kubectl get pods -l app=shard-validation -o wide

# Once you see 4 Running at once, screenshot/keep that output, then:
kubectl get job shard-validation
kubectl wait --for=condition=complete job/shard-validation --timeout=600s

# Collect one shard's result manually (repeat for index 0..7, or use the loop)
kubectl get pods -l "batch.kubernetes.io/job-completion-index=0,app=shard-validation"
kubectl logs -l "batch.kubernetes.io/job-completion-index=0,app=shard-validation"

# Or collect all 8 in one pass with the provided loop (still manual/visible)
for i in 0 1 2 3 4 5 6 7; do
  POD=$(kubectl get pods -l "batch.kubernetes.io/job-completion-index=$i,app=shard-validation" \
          -o jsonpath='{.items[0].metadata.name}')
  echo "--- shard $i ($POD) ---"
  kubectl logs "$POD" | grep RESULT_JSON
done

# Check against ground truth baked into the image
kubectl run gt-check --rm -i --restart=Never --image=spam-shard-validator:v1 \
  --image-pull-policy=IfNotPresent --command -- cat /data/GROUND_TRUTH.txt

# Clean up
kubectl delete -f k8s/q3-indexed-job.yaml
```

---

## Q4: Kubernetes Deployment: self-healing and rolling update

```bash
# Build v1 and v2 images (v2 differs only in APP_VERSION)
docker build -f app/Dockerfile -t spam-api:v1 --build-arg APP_VERSION=1.0.0 ./app
docker build -f app/Dockerfile -t spam-api:v2 --build-arg APP_VERSION=2.0.0 ./app
minikube image load spam-api:v1
minikube image load spam-api:v2

# Deploy
kubectl apply -f k8s/q4-deployment.yaml -f k8s/q4-service.yaml
kubectl rollout status deployment/spam-api
kubectl get pods -l app=spam-api -o wide

URL=$(minikube service spam-api --url | head -1)
curl -s $URL/healthz

### Part 2 — self-healing
kubectl get pods -l app=spam-api -o wide
kubectl get pods -l app=spam-api -o jsonpath='{range .items[*]}{.metadata.name}{" <- owned by "}{.metadata.ownerReferences[0].kind}/{.metadata.ownerReferences[0].name}{"\n"}{end}'

VICTIM=$(kubectl get pods -l app=spam-api -o jsonpath='{.items[0].metadata.name}')
kubectl delete pod "$VICTIM"

kubectl get pods -l app=spam-api -o wide       # run immediately -> shows 1/2, new pod appearing
kubectl wait --for=condition=Ready pod -l app=spam-api --timeout=120s
kubectl get pods -l app=spam-api -o wide       # back to 2/2, different pod name than $VICTIM
kubectl get deployment spam-api

### Part 3 — rolling update
# Start a visible request loop in another terminal (or just run it after, and
# rely on maxUnavailable:0 — either way keep curl calls happening during the update):
#   while true; do curl -s -o /dev/null -w "%{http_code} "  $URL/healthz; sleep 0.2; done

kubectl set image deployment/spam-api api=spam-api:v2
kubectl set env deployment/spam-api APP_VERSION=2.0.0
kubectl annotate deployment spam-api \
  kubernetes.io/change-cause="roll to spam-api:v2" --overwrite

kubectl rollout status deployment/spam-api --timeout=300s
kubectl rollout history deployment/spam-api

kubectl get rs -l app=spam-api                  # old RS at 0, new RS at 2
curl -s $URL/healthz                            # now shows version 2.0.0

curl -s -X POST $URL/predict -H 'Content-Type: application/json' \
  -d '{"text":"URGENT: Your account will be suspended. Verify at win-now.co/claim"}'

# Optional rollback for a second history entry
kubectl rollout undo deployment/spam-api
kubectl rollout history deployment/spam-api

# Clean up
kubectl delete -f k8s/q4-deployment.yaml -f k8s/q4-service.yaml
minikube delete
```

---

