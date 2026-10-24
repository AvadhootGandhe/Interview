"""Warm the speech models at server start so the first interview turn is not ~20 s (model load + JIT)."""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)


async def warm_up_speech(*engines) -> None:
    """Call `warm_up()` on each engine in a worker thread. Never raises: a failed warm-up only costs latency."""
    for engine in engines:
        warm = getattr(engine, "warm_up", None)
        if warm is None:
            continue
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(warm)
            log.info("warmed %s in %.1fs", type(engine).__name__, time.perf_counter() - t0)
        except Exception:  # noqa: BLE001
            log.warning("warm-up of %s failed; first request will be slower", type(engine).__name__, exc_info=True)
