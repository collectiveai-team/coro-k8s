# syntax=docker/dockerfile:1.7
#
# Image of the coro-batch flow runs: the Prefect Kubernetes worker starts one Job
# from it per flow run. Prefect's own image provides Python, prefect and
# prefect-kubernetes; the project and its other dependencies go on top.

ARG PREFECT_IMAGE=prefecthq/prefect:3.9.0-python3.12-kubernetes
ARG UV_VERSION=0.11.12

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-source

FROM ${PREFECT_IMAGE}

# hatch-vcs derives the version from git, which is not in the build context.
ARG CORO_BATCH_VERSION=0.0.0
ENV HATCH_VCS_PRETEND_VERSION=${CORO_BATCH_VERSION} \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1 \
    PREFECT_LOGGING_EXTRA_LOGGERS=coro_batch \
    CORO_BATCH_ENV=prod

COPY --from=uv-source /uv /bin/uv

WORKDIR /opt/coro-batch

# Dependencies first, from the lockfile, so a change of the code reuses the layer.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-emit-project --extra s3 --format requirements.txt \
        > /tmp/requirements.txt \
    && uv pip install --system --requirement /tmp/requirements.txt

COPY coro_batch ./coro_batch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps .
