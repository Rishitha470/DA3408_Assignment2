#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Q3 parts 2 & 3 — capture concurrency evidence, then collect results via the
# Kubernetes API (pod logs). No shared volume is mounted anywhere.
#
# Usage:  ./scripts/q3_collect.sh
# Output: evidence/q3_pods_wide.txt, evidence/q3_results.txt
# ---------------------------------------------------------------------------
set -euo pipefail

JOB=shard-validation
EVID=evidence
mkdir -p "$EVID"

echo "### waiting for pods to appear..."
kubectl wait --for=condition=Ready pod -l app="$JOB" --timeout=120s >/dev/null 2>&1 || true

# ---- part 2: prove the chosen parallelism was actually REACHED -------------
# Poll every 2s and keep the snapshot with the highest simultaneous Running
# count, so the evidence shows real concurrency rather than a lucky moment.
echo "### sampling pod concurrency (this is the parallelism evidence)"
BEST=0
: > "$EVID/q3_pods_wide.txt"
for _ in $(seq 1 60); do
  SNAP=$(kubectl get pods -l app="$JOB" -o wide 2>/dev/null || true)
  RUNNING=$(echo "$SNAP" | grep -c ' Running ' || true)
  if [ "$RUNNING" -gt "$BEST" ]; then
    BEST=$RUNNING
    {
      echo "# snapshot at $(date -u +%H:%M:%SZ) — $RUNNING pods Running concurrently"
      echo "\$ kubectl get pods -l app=$JOB -o wide"
      echo "$SNAP"
      echo
      echo "\$ kubectl get job $JOB"
      kubectl get job "$JOB" 2>/dev/null || true
    } > "$EVID/q3_pods_wide.txt"
  fi
  # stop once the Job has completed
  SUCC=$(kubectl get job "$JOB" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo 0)
  [ "${SUCC:-0}" = "8" ] && break
  sleep 2
done
echo "### peak concurrent Running pods observed: $BEST  (manifest parallelism: 4)"
echo "### snapshot saved to $EVID/q3_pods_wide.txt"

echo
echo "### waiting for the Job to complete..."
kubectl wait --for=condition=complete "job/$JOB" --timeout=600s

# ---- part 3: collect results through the Kubernetes API, per index ---------
# `kubectl logs` is an API call to the kube-apiserver, which proxies to the
# kubelet on whichever node the pod ran on. It is node-agnostic, which is
# exactly the property a hostPath-backed minikube PV does not have.
echo
echo "### collecting per-shard results via the Kubernetes API (pod logs)"
{
  echo "shard | invalid_rows | total_rows | invalid_pct | node | pod"
  echo "------+--------------+------------+-------------+------+----"
  for i in $(seq 0 7); do
    POD=$(kubectl get pods \
            -l "batch.kubernetes.io/job-completion-index=$i,app=$JOB" \
            -o jsonpath='{.items[0].metadata.name}')
    kubectl logs "$POD" | grep '^RESULT_JSON:' | sed 's/^RESULT_JSON://' \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print('%5d | %12d | %10d | %11.2f | %s | %s' % (d['shard_index'], d['invalid_rows'], d['total_rows'], d['invalid_pct'], d['node'], d['pod']))"
  done
} | tee "$EVID/q3_results.txt"

echo
echo "### total invalid rows across all 8 shards:"
TOTAL=0
for i in $(seq 0 7); do
  POD=$(kubectl get pods -l "batch.kubernetes.io/job-completion-index=$i,app=$JOB" \
          -o jsonpath='{.items[0].metadata.name}')
  N=$(kubectl logs "$POD" | grep '^RESULT_JSON:' | sed 's/^RESULT_JSON://' \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['invalid_rows'])")
  TOTAL=$((TOTAL + N))
done
echo "$TOTAL" | tee -a "$EVID/q3_results.txt"
echo
echo "### verify against ground truth baked into the image:"
kubectl run gt-check --rm -i --restart=Never --image=spam-shard-validator:v1 \
  --image-pull-policy=IfNotPresent --command -- cat /data/GROUND_TRUTH.txt \
  | tee -a "$EVID/q3_results.txt"
