# ---------------------------------------------------------------------------
# Q1 part 2 — MULTI-STAGE build. This is also the image used by Q2 (Compose)
# and Q4 (Kubernetes Deployment).
#
# Stage 1 (builder) does everything that needs tools or data:
#   - compiles/downloads wheels with the full toolchain available
#   - installs pandas (needed ONLY to read the CSV during training)
#   - generates spam_dataset.csv and trains model.joblib
# Stage 2 (runtime) copies out exactly two things: a slim virtualenv containing
#   only serving dependencies, and the ~40 KB model.joblib artifact.
# ---------------------------------------------------------------------------

# ----------------------------- stage 1: builder ----------------------------
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# 1a. Training-only environment (pandas lives here and NEVER leaves this stage).
COPY requirements-train.txt ./
RUN pip install --no-cache-dir -r requirements-train.txt

COPY generate_dataset.py train.py ./
RUN python generate_dataset.py && python train.py
# -> /build/spam_dataset.csv  (discarded with this stage)
# -> /build/model.joblib      (the only build product we keep)

# 1b. Runtime virtualenv, built here so that any compilation happens with the
#     toolchain present, but the toolchain itself is left behind.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && find /opt/venv -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /opt/venv -name '*.pyx' -delete \
    && find /opt/venv -name 'tests' -type d -prune -exec rm -rf {} +

# ----------------------------- stage 2: runtime ----------------------------
FROM python:3.11-slim AS runtime

# Q4 part 3: the rolling update is driven by this build arg, so v1 and v2 are
# genuinely different images with a visible difference in GET /healthz.
ARG APP_VERSION=1.0.0

# No apt-get here at all: nothing in the runtime venv needs a compiler.
ENV PATH="/opt/venv/bin:$PATH" \
    MODEL_PATH=/app/model.joblib \
    APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/model.joblib /app/model.joblib
COPY main.py /app/main.py

# Run unprivileged — also what the Q4 Deployment expects.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
