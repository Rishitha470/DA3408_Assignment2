"""Spam-detection REST API.

Contract (as required by the assignment):
  POST /predict  {"text": "..."}  -> {"label": "spam"} | {"label": "ham"}
  GET  /healthz                   -> 200 once the model is loaded

Caching (Q2): if REDIS_HOST is set and reachable, every prediction is looked up
in Redis first.  The JSON body stays EXACTLY as the contract specifies; the
cache verdict and server-side timing are exposed as response headers
(X-Cache: HIT|MISS, X-Elapsed-Ms) so the benchmark can measure them without
breaking the contract.

Redis is OPTIONAL by design: Q1 and Q4 run this same image with no cache
container at all, so a missing/unreachable Redis degrades to compute-every-time
instead of failing the request.
"""
import hashlib
import os
import time
from contextlib import asynccontextmanager

import joblib
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MODEL_PATH = os.getenv("MODEL_PATH", "/app/model.joblib")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
REDIS_HOST = os.getenv("REDIS_HOST", "")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))

STATE = {"model": None, "redis": None, "ready": False}


def _cache_key(text: str) -> str:
    """Hash the input so arbitrarily long / non-ASCII messages stay valid keys."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"spam:v1:{digest}"


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATE["model"] = joblib.load(MODEL_PATH)
    # Warm the vectorizer/classifier so the first real request is not an outlier.
    STATE["model"].predict(["warmup message"])

    if REDIS_HOST:
        try:
            import redis

            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            client.ping()
            STATE["redis"] = client
            print(f"[startup] cache enabled -> {REDIS_HOST}:{REDIS_PORT} ttl={CACHE_TTL_SECONDS}s")
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            STATE["redis"] = None
            print(f"[startup] cache DISABLED ({exc!r}); serving without cache")
    else:
        print("[startup] REDIS_HOST unset; serving without cache")

    STATE["ready"] = True
    print(f"[startup] model loaded from {MODEL_PATH}; version={APP_VERSION}")
    yield
    if STATE["redis"] is not None:
        STATE["redis"].close()


app = FastAPI(title="Spam Detection API", version=APP_VERSION, lifespan=lifespan)


class PredictRequest(BaseModel):
    text: str = Field(..., min_length=1)


@app.get("/healthz")
def healthz():
    """200 only once the model object is actually in memory (K8s readinessProbe)."""
    if not STATE["ready"] or STATE["model"] is None:
        return JSONResponse(status_code=503, content={"status": "loading"})
    return {
        "status": "ok",
        "version": APP_VERSION,
        "cache": "enabled" if STATE["redis"] is not None else "disabled",
    }


@app.post("/predict")
def predict(req: PredictRequest, response: Response):
    started = time.perf_counter()
    cache = STATE["redis"]
    key = _cache_key(req.text)

    if cache is not None:
        try:
            hit = cache.get(key)
        except Exception:  # noqa: BLE001 - never fail a prediction because of the cache
            hit = None
        if hit is not None:
            response.headers["X-Cache"] = "HIT"
            response.headers["X-Elapsed-Ms"] = f"{(time.perf_counter() - started) * 1000:.3f}"
            return {"label": hit}

    label = str(STATE["model"].predict([req.text])[0])

    if cache is not None:
        try:
            cache.setex(key, CACHE_TTL_SECONDS, label)
        except Exception:  # noqa: BLE001
            pass

    response.headers["X-Cache"] = "MISS" if cache is not None else "DISABLED"
    response.headers["X-Elapsed-Ms"] = f"{(time.perf_counter() - started) * 1000:.3f}"
    return {"label": label}


@app.get("/cache/stats")
def cache_stats():
    """Small helper used as evidence in the Q2 write-up."""
    cache = STATE["redis"]
    if cache is None:
        return {"cache": "disabled"}
    info = cache.info("stats")
    return {
        "cache": "enabled",
        "keyspace_hits": info.get("keyspace_hits"),
        "keyspace_misses": info.get("keyspace_misses"),
        "keys": cache.dbsize(),
    }
