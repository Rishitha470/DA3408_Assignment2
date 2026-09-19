#!/usr/bin/env python3
"""Q2 part 3 — measurable cache-hit speedup evidence.

A single before/after curl is not evidence: one prediction takes ~1-3 ms and a
Redis round trip ~0.3 ms, so one sample is dominated by noise. This script
instead:

  1. sends N *unique* messages   -> every request is a guaranteed cache MISS
  2. replays the same N messages -> every request is a guaranteed cache HIT
  3. reports mean / p50 / p95 for each population and the speedup factor

It asserts the HIT population is strictly faster and that both populations
return the same labels (i.e. caching did not change correctness).

Usage:
    python scripts/bench_cache.py                 # defaults: 200 requests
    python scripts/bench_cache.py --n 500 --url http://localhost:8000
"""
import argparse
import json
import statistics
import time
import urllib.error
import urllib.request

SPAM_SEED = "WIN a FREE {p} now! Click here: bit.ly/xyz123 [{i}]"
HAM_SEED = "Hey, are we still meeting for lunch on Friday? [{i}]"
PRIZES = ["iPhone", "cash prize", "gift card", "vacation", "laptop"]


def post_predict(url: str, text: str):
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url + "/predict", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.load(resp)
        cache_state = resp.headers.get("X-Cache", "?")
        server_ms = float(resp.headers.get("X-Elapsed-Ms", "nan"))
    wall_ms = (time.perf_counter() - t0) * 1000
    return payload["label"], cache_state, server_ms, wall_ms


def wait_ready(url: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=3) as r:
                if r.status == 200:
                    print(f"[ready] {json.load(r)}")
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    raise SystemExit(f"API at {url} never became ready")


def run(url: str, messages, label: str):
    labels, server, wall, states = [], [], [], set()
    for m in messages:
        lab, state, s_ms, w_ms = post_predict(url, m)
        labels.append(lab)
        server.append(s_ms)
        wall.append(w_ms)
        states.add(state)
    print(
        f"[{label:5}] n={len(messages):4d}  X-Cache={sorted(states)}  "
        f"server mean={statistics.mean(server):7.3f} ms  "
        f"p50={statistics.median(server):7.3f} ms  "
        f"p95={sorted(server)[int(0.95 * len(server)) - 1]:7.3f} ms  |  "
        f"wall mean={statistics.mean(wall):7.3f} ms"
    )
    return labels, statistics.mean(server), statistics.median(server), statistics.mean(wall)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    wait_ready(args.url)

    # Unique per-run suffix so a re-run is not accidentally served from a warm cache.
    run_id = int(time.time())
    msgs = [
        (SPAM_SEED if i % 3 == 0 else HAM_SEED).format(p=PRIZES[i % len(PRIZES)], i=f"{run_id}-{i}")
        for i in range(args.n)
    ]

    # Warm-up: exercise the code path a few times so JIT/alloc effects don't
    # land entirely on the MISS population.
    for m in msgs[:5]:
        post_predict(args.url, m + " warmup")

    print("\n=== Q2 cache benchmark ===")
    miss_labels, miss_mean, miss_p50, miss_wall = run(args.url, msgs, "MISS")
    hit_labels, hit_mean, hit_p50, hit_wall = run(args.url, msgs, "HIT")

    assert miss_labels == hit_labels, "cache returned different labels than the model!"
    print(f"\ncorrectness: all {len(msgs)} labels identical on hit and miss  -> OK")
    print(f"speedup (server mean): {miss_mean / hit_mean:.2f}x   "
          f"({miss_mean:.3f} ms -> {hit_mean:.3f} ms)")
    print(f"speedup (server p50) : {miss_p50 / hit_p50:.2f}x   "
          f"({miss_p50:.3f} ms -> {hit_p50:.3f} ms)")
    print(f"speedup (wall  mean) : {miss_wall / hit_wall:.2f}x")

    try:
        with urllib.request.urlopen(args.url + "/cache/stats", timeout=5) as r:
            print(f"redis stats: {json.load(r)}")
    except Exception as exc:  # noqa: BLE001
        print(f"(cache stats unavailable: {exc})")

    if hit_mean >= miss_mean:
        raise SystemExit("FAIL: cache hits were not faster than misses")
    print("\nRESULT: cache hits are measurably faster than misses.")


if __name__ == "__main__":
    main()
