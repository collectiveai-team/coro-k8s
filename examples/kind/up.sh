#!/usr/bin/env sh
# Stand up coro, Prefect and the demo services on a local kind cluster.
#
# Needs docker, kind, kubectl, helm and uv. Run from the root of the repository.
# The coro image is several GB; it is pulled once and loaded into the node.
set -eu

CLUSTER=coro-k8s
CORO_IMAGE="${CORO_IMAGE:-ghcr.io/collectiveai-team/coro:1.7.0-cpu}"
BATCH_IMAGE="${BATCH_IMAGE:-coro-batch:dev}"
PREFECT_CHART_VERSION=2026.10.30155115
JFK_URL=https://raw.githubusercontent.com/collectiveai-team/coro/v1.7.0/coro/bench/data/jfk.wav

step() { printf '\n== %s\n' "$*"; }

step "cluster"
kind get clusters | grep -qx "$CLUSTER" || kind create cluster --config examples/kind/cluster.yaml

step "images"
docker build --tag "$BATCH_IMAGE" .
docker image inspect "$CORO_IMAGE" >/dev/null 2>&1 || docker pull "$CORO_IMAGE"
kind load docker-image --name "$CLUSTER" "$CORO_IMAGE" "$BATCH_IMAGE"

step "coro"
helm upgrade --install coro charts/coro --namespace coro --create-namespace \
    --values examples/kind/coro-values.yaml

step "prefect"
helm repo add prefect https://prefecthq.github.io/prefect-helm >/dev/null
helm repo update prefect >/dev/null
helm upgrade --install prefect-server prefect/prefect-server \
    --version "$PREFECT_CHART_VERSION" --namespace prefect --create-namespace \
    --values deploy/prefect/server-values.yaml --values examples/kind/prefect-server-values.yaml
helm upgrade --install prefect-worker prefect/prefect-worker \
    --version "$PREFECT_CHART_VERSION" --namespace prefect \
    --values deploy/prefect/worker-values.yaml

step "demo services"
kubectl apply --filename examples/kind/demo.yaml
mkdir -p .tmp/demo
[ -f .tmp/demo/jfk.wav ] || curl -fsSL --retry 3 -o .tmp/demo/jfk.wav "$JFK_URL"
kubectl --namespace demo create configmap demo-audio --from-file=jfk.wav=.tmp/demo/jfk.wav \
    --dry-run=client --output yaml | kubectl apply --server-side --filename -

step "waiting for the rollouts (coro downloads its model and warms up)"
kubectl --namespace demo rollout status deployment/audio --timeout=5m
kubectl --namespace demo rollout status deployment/callback-receiver --timeout=5m
kubectl --namespace prefect rollout status deployment/prefect-server --timeout=10m
kubectl --namespace prefect rollout status deployment/prefect-worker --timeout=10m
kubectl --namespace coro rollout status deployment/coro --timeout=30m
helm test coro --namespace coro --timeout 10m --logs

step "ready: run examples/kind/run-demo.sh"
