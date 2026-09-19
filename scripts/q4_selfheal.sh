#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Q4 part 2 — self-healing evidence: delete a pod, show Kubernetes recreate it.
# Output: evidence/q4_selfheal.txt
# ---------------------------------------------------------------------------
set -euo pipefail
EVID=evidence
mkdir -p "$EVID"
exec > >(tee "$EVID/q4_selfheal.txt") 2>&1

echo "=== BEFORE: pods and the ReplicaSet that owns them ==="
kubectl get pods -l app=spam-api -o wide
echo
kubectl get rs -l app=spam-api
echo
echo "ownerReferences of one pod (proves the ReplicaSet, not the Deployment, owns it):"
kubectl get pods -l app=spam-api -o jsonpath='{range .items[*]}{.metadata.name}{" <- owned by "}{.metadata.ownerReferences[0].kind}{"/"}{.metadata.ownerReferences[0].name}{"\n"}{end}'

VICTIM=$(kubectl get pods -l app=spam-api -o jsonpath='{.items[0].metadata.name}')
echo
echo "=== DELETING pod: $VICTIM ==="
kubectl delete pod "$VICTIM"

echo
echo "=== IMMEDIATELY AFTER (replacement already being created) ==="
kubectl get pods -l app=spam-api -o wide

echo
echo "=== Deployment events showing the controller reacting ==="
kubectl get events --field-selector involvedObject.kind=Pod \
  --sort-by=.lastTimestamp 2>/dev/null | tail -12

echo
echo "=== waiting for the replacement to become Ready ==="
kubectl wait --for=condition=Ready pod -l app=spam-api --timeout=120s

echo
echo "=== AFTER: back to 2/2, with a NEW pod name replacing $VICTIM ==="
kubectl get pods -l app=spam-api -o wide
echo
kubectl get deployment spam-api
echo
echo "NOTE: the new pod has a different name and a fresh AGE, and $VICTIM is gone."
