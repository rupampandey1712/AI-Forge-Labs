# syntax=docker/dockerfile:1.7
#
# THE SANDBOX SERVICE (spec §35, §66)
#
# This is the *service* that wraps code execution, as distinct from
# `sandbox.Dockerfile`, which is the per-execution jail. Two images, two jobs:
#
#   sandbox-service.Dockerfile   a long-lived HTTP server, one endpoint
#   sandbox.Dockerfile           a throwaway container, one execution, no net
#
# In SANDBOX_MODE=docker the service starts one jail container per submission.
# In SANDBOX_MODE=subprocess it runs the same `runner_main.py` as a resource-
# limited child process, which is what Container Apps uses because nested
# Docker is not available there.
#
# WHAT IS DELIBERATELY NOT IN THIS IMAGE:
#   - the game's models, services or API routes
#   - a database driver or any connection string
#   - the JWT signing key or any game secret
#
# It copies `app/sandbox/` and nothing else from the application. The boundary
# is enforced by a test, not by discipline:
#   tests/integration/test_sandbox_service.py::test_the_service_imports_nothing_from_the_game
#
# Build:
#   docker build -f infra/docker/sandbox-service.Dockerfile -t aiforge-sandbox-service backend

# ─── Build ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only what the service itself needs. Notably absent: sqlalchemy, asyncpg,
# alembic, pyjwt, bcrypt. The service has no database and no user concept, so
# installing those would be adding attack surface to buy nothing — and it would
# let a future change quietly reach for them.
RUN pip install --no-cache-dir \
      "fastapi>=0.115" \
      "uvicorn[standard]>=0.32" \
      "structlog>=24.4" \
      "numpy>=1.26" \
      "pandas>=2.2" \
      "scikit-learn>=1.5"

# ─── Runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv

# The only application code in the image. `app/core/logging.py` comes along
# because app.sandbox imports get_logger from it; that module reads no settings
# and holds no secrets, which is why it is an acceptable dependency and
# app/core/config.py is not.
COPY app/__init__.py /srv/app/__init__.py
COPY app/core/__init__.py /srv/app/core/__init__.py
COPY app/core/logging.py /srv/app/core/logging.py
COPY app/sandbox /srv/app/sandbox

# Unprivileged, and without a login shell: if something escapes the interpreter
# it lands as a user that cannot log in and owns nothing in the filesystem.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 10001 sandboxsvc \
 && chown -R root:root /srv \
 && chmod -R a-w /srv

USER 10001:10001

EXPOSE 8001

# No --reload, no --workers. One worker per container and let the orchestrator
# scale replicas: two workers in one container share a CPU quota, so a heavy
# submission in one degrades the other and every timing measurement the
# benchmark challenges make becomes noise.
CMD ["uvicorn", "app.sandbox.server:app", "--host", "0.0.0.0", "--port", "8001"]
