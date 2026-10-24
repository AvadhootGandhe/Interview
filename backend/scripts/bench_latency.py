"""Turn latency benchmark (goal G4: p50 < 4 s). Runs against a live server.

    python scripts/bench_latency.py --base http://localhost:8000 --turns 12
"""
import argparse
import math
import statistics
import sys
import time

import httpx

ANSWER = "I would shard by tenant, add a write-through cache, and watch replication lag and failure modes."


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile; 0.0 for no data."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--profile", default="Backend")
    ap.add_argument("--level", default="SDE-2/3")
    ap.add_argument("--company", default=None)
    args = ap.parse_args()
    times: list[float] = []
    with httpx.Client(base_url=args.base, timeout=120) as http:
        sid = http.post("/sessions", json={"profile": args.profile, "level": args.level,
                                           "company": args.company}).json()["session_id"]
        for _ in range(args.turns):
            start = time.perf_counter()
            r = http.post(f"/sessions/{sid}/answer", json={"text": ANSWER}).json()
            times.append(time.perf_counter() - start)
            if r["state"] == "done":
                break
    p50, p95 = percentile(times, 50), percentile(times, 95)
    print(f"{len(times)} turns  p50 {p50:.2f}s  p95 {p95:.2f}s  mean {statistics.mean(times):.2f}s  "
          f"(targets: p50 < 4s, p95 < 6s)")
    sys.exit(0 if p50 < 4 else 1)


if __name__ == "__main__":
    main()
