"""Q3 — validate exactly ONE shard, selected by the Indexed Job's completion index.

Kubernetes injects JOB_COMPLETION_INDEX (0..completions-1) into every pod of an
Indexed Job; POD_NAME and NODE_NAME come from the Downward API fields declared
in the manifest.

Results are written to STDOUT only. They are collected afterwards through the
Kubernetes API (`kubectl logs`), never through a shared volume — see the
write-up for why minikube's hostPath-backed `standard` StorageClass cannot give
us a cross-node ReadWriteMany volume.

The final line is a single-line JSON object prefixed with RESULT_JSON:, which
makes the collector a trivial grep rather than a log parser.
"""
import csv
import json
import os
import re
import sys
import time

# Deliberately stricter than "contains an @": local@label(.label)+ with a
# 2+ char TLD, no leading/trailing/double dots, no whitespace.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,}$"
)
REQUIRED_FIELDS = ("user_id", "signup_date", "country")


def validate_row(row: dict):
    """Return a list of reason strings; empty list means the row is valid."""
    reasons = []
    for field in REQUIRED_FIELDS:
        if not (row.get(field) or "").strip():
            reasons.append(f"missing:{field}")
    email = (row.get("email") or "").strip()
    if not email:
        reasons.append("missing:email")
    elif not EMAIL_RE.match(email):
        reasons.append("malformed:email")
    return reasons


def main() -> int:
    index = os.getenv("JOB_COMPLETION_INDEX")
    if index is None:
        print("JOB_COMPLETION_INDEX is not set — is this an Indexed Job?", file=sys.stderr)
        return 2

    pod_name = os.getenv("POD_NAME", "<unknown-pod>")
    node_name = os.getenv("NODE_NAME", "<unknown-node>")
    data_dir = os.getenv("DATA_DIR", "/data")
    shard_path = os.path.join(data_dir, f"shard_{index}.csv")

    print(f"[pod={pod_name}] [node={node_name}] [index={index}] validating {shard_path}",
          flush=True)

    if not os.path.exists(shard_path):
        print(f"shard not found: {shard_path}", file=sys.stderr)
        return 1

    started = time.perf_counter()
    total = invalid = 0
    reason_counts: dict[str, int] = {}
    samples = []

    with open(shard_path, newline="", encoding="utf-8") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            total += 1
            reasons = validate_row(row)
            if reasons:
                invalid += 1
                for r in reasons:
                    reason_counts[r] = reason_counts.get(r, 0) + 1
                if len(samples) < 3:
                    samples.append({"line": line_no,
                                    "user_id": row.get("user_id", ""),
                                    "email": row.get("email", ""),
                                    "reasons": reasons})

    elapsed = time.perf_counter() - started
    for s in samples:
        print(f"  invalid sample line {s['line']}: {s['reasons']} "
              f"user_id={s['user_id']!r} email={s['email']!r}", flush=True)

    result = {
        "shard_index": int(index),
        "pod": pod_name,
        "node": node_name,
        "total_rows": total,
        "invalid_rows": invalid,
        "valid_rows": total - invalid,
        "invalid_pct": round(100.0 * invalid / total, 2) if total else 0.0,
        "reason_counts": reason_counts,
        "elapsed_seconds": round(elapsed, 4),
    }
    print("RESULT_JSON:" + json.dumps(result, sort_keys=True), flush=True)

    # Hold the pod alive briefly so that `kubectl get pods -o wide` can actually
    # catch the configured parallelism running concurrently (part 2 evidence).
    # Set HOLD_SECONDS=0 to disable.
    hold = float(os.getenv("HOLD_SECONDS", "20"))
    if hold > 0:
        print(f"[pod={pod_name}] holding {hold:.0f}s for concurrency evidence", flush=True)
        time.sleep(hold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
