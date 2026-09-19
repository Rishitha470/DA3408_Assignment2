# ---------------------------------------------------------------------------
# Q3 — shard-validator image.
#
# The 8 shards are GENERATED IN THE BUILDER and baked into the runtime image.
# This is the deliberate consequence of the no-shared-volume decision: with
# minikube's hostPath-backed `standard` StorageClass there is no cross-node
# ReadWriteMany volume available, so input travels in the image and output
# travels back out through the Kubernetes API (pod logs).
#
# Multi-stage again, for the same reason as Q1: the generator script and its
# interpreter scratch files stay in the builder; only the CSVs come forward.
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS builder
WORKDIR /build
COPY generate_shards.py ./
RUN python generate_shards.py
# -> /build/shards/shard_0.csv .. shard_7.csv + GROUND_TRUTH.txt

FROM python:3.11-slim AS runtime
# Pure stdlib validator: csv + re + json. No pip install at all, so the runtime
# image is just the slim base plus ~250 KB of CSV.
WORKDIR /app
COPY --from=builder /build/shards /data
COPY validate_shard.py /app/validate_shard.py

ENV DATA_DIR=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 validator
USER validator

ENTRYPOINT ["python", "/app/validate_shard.py"]
