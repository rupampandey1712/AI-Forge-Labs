# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the game server.
#
# WHY multi-stage: the build stage needs a compiler toolchain (asyncpg and
# bcrypt build native extensions); the runtime does not. Shipping gcc in a
# production image is ~250MB of attack surface for zero benefit.
#
# WHY a virtualenv rather than --user or a system install: copying one
# self-contained /opt/venv directory between stages is simpler and more
# predictable than replicating pip's site-packages layout.

# ─── Build ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install --no-install-recommends -y \
      build-essential \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Dependency layer first: pyproject changes far less often than app code, so
# this layer is cached across almost every rebuild.
COPY pyproject.toml ./
COPY app/__init__.py ./app/
RUN pip install --upgrade pip setuptools wheel \
    && pip install -e ".[dev]"

# ─── Runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production

# libpq5 is the runtime half of libpq-dev; curl is for the container healthcheck.
RUN apt-get update && apt-get install --no-install-recommends -y \
      libpq5 \
      curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin forge

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=forge:forge . .

# Drop privileges. A container running as root that also executes player-
# submitted code would be indefensible, even with the sandbox in front of it.
USER forge

EXPOSE 8000

# Distinguishes "the process is wedged" from "a dependency is down": /health/live
# touches nothing, so a failure here genuinely means restart me.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1

# One worker per container; scale with replicas, not with --workers. Multiple
# workers inside one container hide per-worker memory growth and make the
# in-process sandbox semaphore meaningless.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--no-access-log"]
