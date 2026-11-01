#!/usr/bin/env sh
# Lint the coro chart and validate what it renders against the Kubernetes schemas.
#
# For each values file under charts/coro/ci/: `helm lint --strict`, then
# `helm template` piped to kubeconform. kubeconform runs from its image, pinned by
# version and digest. CRDs (KEDA ScaledObject, ServiceMonitor) are checked against
# the datreeio CRDs catalog, so the script needs the network.
#
# Usage: scripts/check-chart.sh [kubernetes-version]
set -eu

KUBERNETES_VERSION="${1:-1.31.0}"
CHART=charts/coro
KUBECONFORM="ghcr.io/yannh/kubeconform:v0.7.0@sha256:85dbef6b4b312b99133decc9c6fc9495e9fc5f92293d4ff3b7e1b30f5611823c"
CRDS_CATALOG='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

for values in "$CHART"/ci/*-values.yaml; do
    echo "== $values"
    helm lint --strict "$CHART" --values "$values" --quiet
    helm template coro "$CHART" --namespace coro --values "$values" \
        | docker run --rm -i "$KUBECONFORM" \
            -strict -summary \
            -kubernetes-version "$KUBERNETES_VERSION" \
            -schema-location default \
            -schema-location "$CRDS_CATALOG"
done
