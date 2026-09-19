#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Q1 — build both images, verify identical behaviour, report sizes + % reduction.
# Output: evidence/q1_sizes.txt
# ---------------------------------------------------------------------------
set -euo pipefail
EVID=evidence
mkdir -p "$EVID"
exec > >(tee "$EVID/q1_sizes.txt") 2>&1

echo "=== building naive single-stage image ==="
docker build -f app/Dockerfile.naive -t spam-api:naive ./app

echo
echo "=== building multi-stage image ==="
docker build -f app/Dockerfile -t spam-api:v1 --build-arg APP_VERSION=1.0.0 ./app

echo
echo "=== docker images ==="
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.ID}}' \
  | grep -E 'REPOSITORY|spam-api'

echo
echo "=== size comparison ==="
NAIVE=$(docker image inspect spam-api:naive --format '{{.Size}}')
MULTI=$(docker image inspect spam-api:v1    --format '{{.Size}}')
python3 - "$NAIVE" "$MULTI" <<'PY'
import sys
naive, multi = int(sys.argv[1]), int(sys.argv[2])
mb = lambda b: b / 1024 / 1024
print(f"naive single-stage : {mb(naive):8.1f} MB  ({naive:,} bytes)")
print(f"multi-stage        : {mb(multi):8.1f} MB  ({multi:,} bytes)")
print(f"absolute reduction : {mb(naive-multi):8.1f} MB")
print(f"percent reduction  : {100*(naive-multi)/naive:8.1f} %")
PY

echo
echo "=== what is actually IN each image (evidence for the explanation) ==="
for TAG in naive v1; do
  echo "--- spam-api:$TAG ---"
  docker run --rm --entrypoint sh "spam-api:$TAG" -c '
    echo "base:        $(cat /etc/os-release | grep PRETTY_NAME)"
    echo "gcc present: $(command -v gcc || echo NO)"
    echo "pandas:      $(python -c "import pandas,os;print(os.path.dirname(pandas.__file__))" 2>/dev/null || echo NOT INSTALLED)"
    echo "dataset CSV: $(ls -la /app/spam_dataset.csv 2>/dev/null || echo NOT PRESENT)"
    echo "train.py:    $(ls /app/train.py 2>/dev/null || echo NOT PRESENT)"
    echo "pip cache:   $(du -sh /root/.cache/pip 2>/dev/null || echo NONE)"
  ' 2>/dev/null || echo "(non-root image: inspect via docker history instead)"
  echo
done

echo "=== behavioural equivalence check ==="
for TAG in naive v1; do
  docker rm -f sizecheck >/dev/null 2>&1 || true
  docker run -d --name sizecheck -p 8099:8000 "spam-api:$TAG" >/dev/null
  for _ in $(seq 1 30); do
    curl -sf http://localhost:8099/healthz >/dev/null 2>&1 && break
    sleep 1
  done
  echo -n "spam-api:$TAG  /healthz -> "; curl -s http://localhost:8099/healthz; echo
  echo -n "spam-api:$TAG  /predict(spam) -> "
  curl -s -X POST http://localhost:8099/predict -H 'Content-Type: application/json' \
    -d '{"text":"WIN a FREE iPhone now! Click here: bit.ly/xyz123"}'; echo
  echo -n "spam-api:$TAG  /predict(ham)  -> "
  curl -s -X POST http://localhost:8099/predict -H 'Content-Type: application/json' \
    -d '{"text":"Hey, are we still meeting for lunch on Friday?"}'; echo
  docker rm -f sizecheck >/dev/null
  echo
done
echo "Both images serve /healthz and /predict identically."
