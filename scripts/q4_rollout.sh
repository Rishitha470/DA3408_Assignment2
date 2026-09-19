#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Q4 part 3 — rolling update evidence.
#
# Runs a continuous request loop against the Service THROUGHOUT the update and
# counts failures, so "without downtime" is measured, not asserted. Also
# records the moment /healthz starts reporting version 2.0.0.
#
# Prerequisite: spam-api:v2 has been built and loaded (see README).
# Output: evidence/q4_rollout.txt, evidence/q4_downtime_probe.txt
# ---------------------------------------------------------------------------
set -euo pipefail
EVID=evidence
mkdir -p "$EVID"

URL=$(minikube service spam-api --url 2>/dev/null | head -1)
echo "probing $URL"

# ---- start the background downtime probe ----------------------------------
cat > /tmp/probe.sh <<'PROBE'
#!/usr/bin/env bash
URL="$1"; OUT="$2"
OK=0; FAIL=0; V1=0; V2=0
: > "$OUT"
while [ ! -f /tmp/probe.stop ]; do
  BODY=$(curl -s -m 2 -o - -w '\n%{http_code}' "$URL/healthz" 2>/dev/null || echo $'\n000')
  CODE=$(echo "$BODY" | tail -1)
  if [ "$CODE" = "200" ]; then
    OK=$((OK+1))
    echo "$BODY" | grep -q '"2.0.0"' && V2=$((V2+1)) || V1=$((V1+1))
  else
    FAIL=$((FAIL+1))
    echo "$(date -u +%H:%M:%S.%3NZ) NON-200: $CODE" >> "$OUT"
  fi
  sleep 0.1
done
{
  echo "--- downtime probe summary ---"
  echo "successful (HTTP 200) : $OK"
  echo "failed     (non-200)  : $FAIL"
  echo "  served by v1.0.0    : $V1"
  echo "  served by v2.0.0    : $V2"
} >> "$OUT"
PROBE
chmod +x /tmp/probe.sh
rm -f /tmp/probe.stop
/tmp/probe.sh "$URL" "$EVID/q4_downtime_probe.txt" &
PROBE_PID=$!
sleep 3

# ---- perform the rolling update -------------------------------------------
{
  echo "=== BEFORE: current image and version ==="
  kubectl get deployment spam-api -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
  curl -s "$URL/healthz"; echo
  kubectl get pods -l app=spam-api -o wide
  echo
  echo "=== triggering rolling update to spam-api:v2 ==="
  kubectl set image deployment/spam-api api=spam-api:v2
  kubectl set env deployment/spam-api APP_VERSION=2.0.0
  kubectl annotate deployment spam-api \
    kubernetes.io/change-cause="roll to spam-api:v2 — /healthz now reports version 2.0.0" --overwrite
  echo
  echo "=== kubectl rollout status ==="
  kubectl rollout status deployment/spam-api --timeout=300s
  echo
  echo "=== kubectl rollout history ==="
  kubectl rollout history deployment/spam-api
  echo
  echo "=== AFTER: new image, new version, both pods replaced ==="
  kubectl get deployment spam-api -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
  curl -s "$URL/healthz"; echo
  kubectl get pods -l app=spam-api -o wide
  echo
  echo "=== ReplicaSets: old scaled to 0, new scaled to 2 ==="
  kubectl get rs -l app=spam-api
  echo
  echo "=== prediction still correct on the new revision ==="
  curl -s -X POST "$URL/predict" -H 'Content-Type: application/json' \
    -d '{"text":"WIN a FREE iPhone now! Click here: bit.ly/xyz123"}'; echo
  curl -s -X POST "$URL/predict" -H 'Content-Type: application/json' \
    -d '{"text":"Hey, are we still meeting for lunch on Friday?"}'; echo
} | tee "$EVID/q4_rollout.txt"

sleep 3
touch /tmp/probe.stop
wait $PROBE_PID 2>/dev/null || true
echo
echo "=== downtime probe result ==="
cat "$EVID/q4_downtime_probe.txt"
