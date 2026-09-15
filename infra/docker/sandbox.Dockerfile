# syntax=docker/dockerfile:1.7
#
# THE CODE EXECUTION SANDBOX (spec §35, §66)
#
# This image runs player-submitted code. Read the whole comment before changing
# anything in it.
#
# What is deliberately NOT here:
#   - application code (no app/, no models, no config)
#   - a database driver or any connection string
#   - secrets of any kind
#   - a shell for the runtime user
#   - network tooling (curl, wget)
#
# The only thing copied in is `runner_main.py`, which is standalone by design —
# `tests/integration/test_sandbox_security.py::test_runner_imports_nothing_from_the_app`
# enforces that. If someone escapes the interpreter inside this container, they
# land in an empty filesystem with no network and no credentials.
#
# The container is started per-execution by app/sandbox/backends.py with:
#   --network none --read-only --cap-drop ALL --security-opt no-new-privileges
#   --user 65534 --pids-limit 64 --memory <limit> --memory-swap <same> --cpus 1
#
# Build:  docker build -f infra/docker/sandbox.Dockerfile -t aiforge-sandbox:latest backend
# Enable: SANDBOX_MODE=docker

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The scientific stack, because the NumPy/Pandas/Matplotlib/ML labs need it
# *inside* the sandbox — the game server never imports player code, so these
# cannot live there.
#
# Torch is intentionally omitted from the default image: it is ~2GB and would
# make every sandbox pull painful. Build the `ml` variant below when the Deep
# Learning Lab is in use.
RUN pip install --no-cache-dir \
      "numpy>=1.26" \
      "pandas>=2.2" \
      "matplotlib>=3.9" \
      "scikit-learn>=1.5" \
 && rm -rf /root/.cache

# Matplotlib must not try to open a display, and must not write a font cache
# into a read-only filesystem on first import.
ENV MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl

# Warm the font cache at build time so the read-only runtime never needs to.
RUN python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot" || true

WORKDIR /sandbox

# The ONLY application file in the image.
COPY app/sandbox/runner_main.py /sandbox/runner_main.py

# nobody:nogroup. Nothing in the image is owned by it, and the rootfs is
# mounted read-only at runtime anyway — this is belt and braces.
USER 65534:65534

# `-I` is isolated mode: ignores PYTHON* environment variables and the user
# site directory, so a crafted env cannot inject an import path.
ENTRYPOINT ["python", "-I", "-B", "/sandbox/runner_main.py"]
