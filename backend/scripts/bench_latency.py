"""Latency bench (local): end of answer -> interviewer audio ready, against a running server.

    # fake everything (plumbing only, NOT a G4 measurement):
    FAKE_LLM=1 SPEECH=fake uvicorn app.main:app --port 8000
    # real Claude + real speech (G4):
    ANTHROPIC_API_KEY=... SPEECH=real uvicorn app.main:app --port 8000
    python scripts/bench_latency.py --url http://127.0.0.1:8000 --turns 5 [--text]

Each turn posts the answer (hello.wav through STT, or typed text with --text), then fetches the returned
audio_url; the clock stops when the audio bytes arrive. Stage timings come from the Server-Timing header.
G4 is only claimed when the server ran with a real ANTHROPIC_API_KEY (the script reports which it assumes).
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import time
from pathlib import Path

import httpx

HELLO = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "hello.wav"
TYPED = "I would put a queue in front of the service, cache hot reads, and shard by user id."
STAGES = ["stt", "evaluate", "flow", "interviewer", "tts", "total"]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[k]


def parse_server_timing(header: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in header.split(","):
        name, _, rest = part.strip().partition(";dur=")
        if rest:
            out[name] = float(rest)
    return out


def run(url: str, turns: int, typed: bool, profile: str, level: str) -> dict:
    wall: list[float] = []
    stages: dict[str, list[float]] = {s: [] for s in STAGES}
    audio_missing = 0
    audio = HELLO.read_bytes()
    with httpx.Client(base_url=url, timeout=120) as c:
        sid = None
        for _ in range(turns):
            if sid is None:
                r = c.post("/sessions", json={"profile": profile, "level": level})
                r.raise_for_status()
                sid = r.json()["session_id"]
            t0 = time.perf_counter()
            if typed:
                r = c.post(f"/sessions/{sid}/answer", json={"text": TYPED})
            else:
                r = c.post(f"/sessions/{sid}/answer", files={"audio": ("hello.wav", audio, "audio/wav")})
            r.raise_for_status()
            data = r.json()
            if data.get("audio_url"):
                c.get(data["audio_url"]).raise_for_status()
            else:
                audio_missing += 1
            wall.append((time.perf_counter() - t0) * 1000)
            for k, v in parse_server_timing(r.headers.get("server-timing", "")).items():
                if k in stages:
                    stages[k].append(v)
            if data["done"]:
                sid = None
    return {"wall": wall, "stages": stages, "audio_missing": audio_missing}


def report(res: dict, real_llm: bool, typed: bool) -> str:
    w = res["wall"]
    lines = [
        f"LLM: {'REAL Claude (ANTHROPIC_API_KEY set)' if real_llm else 'FAKE (plumbing only, not a G4 measurement)'}"
        f" | input: {'typed' if typed else 'audio'} | turns: {len(w)} | turns without audio_url: {res['audio_missing']}",
        f"end-of-answer -> audio ready: p50 {percentile(w, 50) / 1000:.2f}s  p95 {percentile(w, 95) / 1000:.2f}s"
        f"  (G4 target p50 < 4s: {'PASS' if percentile(w, 50) < 4000 else 'FAIL'}"
        f"{'' if real_llm else ', not valid with fakes'})",
        "stage (ms)        p50      p95",
    ]
    for s in STAGES:
        v = res["stages"][s]
        if v:
            lines.append(f"  {s:<12} {statistics.median(v):8.1f} {percentile(v, 95):8.1f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--text", action="store_true", help="send typed answers instead of hello.wav")
    ap.add_argument("--profile", default="Backend")
    ap.add_argument("--level", default="SDE-2/3")
    a = ap.parse_args()
    print(report(run(a.url, a.turns, a.text, a.profile, a.level), bool(os.environ.get("ANTHROPIC_API_KEY")), a.text))


if __name__ == "__main__":
    main()
