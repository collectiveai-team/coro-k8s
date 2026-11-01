# coro chart

Runs [coro](https://github.com/collectiveai-team/coro) as a Deployment behind a
ClusterIP Service. The image is `ghcr.io/collectiveai-team/coro:<appVersion>-<flavor>`.

```sh
helm install coro charts/coro --namespace coro --create-namespace --values my-values.yaml
helm test coro --namespace coro --logs   # transcribes the JFK clip through the Service
```

## Sizing a replica

One coro process per pod; scale with replicas, not uvicorn workers. coro sizes
its ASR permits from the cores it may use: with `CORO_ASR_MAX_CONCURRENCY=0`
it is one permit per 4 cores. coro 1.6.0 reads the cores of the node, not the
CPU limit, so set `CORO_ASR_MAX_CONCURRENCY` explicitly until a release reads
the limit.

`resources` defaults to 4 CPUs and 8 GiB with requests equal to limits
(Guaranteed QoS). Under the kubelet's static CPU manager policy the pod then
gets exclusive cores, and its CPU affinity equals its limit.

For GPU: `image.flavor: gpu`, `gpu.enabled: true`, and the tolerations or
node selector of your GPU nodes. One replica per GPU.

## Values

| Key | Default | Meaning |
|---|---|---|
| `image.flavor` | `cpu` | `cpu` or `gpu`. |
| `coro.env` | see values.yaml | `CORO_*` variables of the server. |
| `coro.hfTokenSecret.name` | | Secret with `HF_TOKEN` for gated models. |
| `coro.forwardedAllowIps` | `*` | Proxies whose `X-Forwarded-For` coro trusts. |
| `resources` | 4 CPU, 8Gi | Requests and limits. |
| `modelCache.existingClaim` / `create` | emptyDir | Hugging Face cache. A ReadWriteMany claim lets replicas share it. |
| `spill.sizeLimit` | `20Gi` | Disk-backed emptyDir for the streaming pipeline's spill. |
| `probes.startup.failureThreshold` | `120` | x 10 s: the time to download models and warm up. |
| `terminationGracePeriodSeconds` | `3600` | uvicorn waits for requests in flight on SIGTERM. |
| `autoscaling.mode` | `none` | `hpa` (CPU) or `keda` (queued ASR work). |
| `metrics.serviceMonitor.enabled` | `false` | Prometheus Operator scrape of `/metrics`. |
| `networkPolicy.enabled` / `from` | `false` | Allow only these peers to the HTTP port. |
| `ingress.enabled` | `false` | With nginx annotations for long requests and large bodies. |
| `podDisruptionBudget.enabled` | `false` | `maxUnavailable: 1`. |

## Autoscaling on queued work

`autoscaling.mode: keda` creates a KEDA ScaledObject whose Prometheus query is

```
(sum(coro_asr_inferences_queued) + sum(coro_asr_inferences_in_flight)) / sum(coro_asr_inference_permits)
```

over the pods of the Service: ASR calls waiting or running per permit. With
`metricType: Value` the replica count scales by that ratio over
`autoscaling.keda.targetLoadPerPermit`. It needs KEDA, a Prometheus that scrapes
coro (`metrics.serviceMonitor.enabled`), and a coro release with `GET /metrics`
(after 1.6.0). Scale-down waits `cooldownPeriod` (600 s) because a new replica
takes minutes to warm up.

## Limits of coro to keep in mind

- No authentication: keep the Service internal or behind an authenticating proxy.
- Rate limits are per replica (`CORO_RATE_LIMIT_*`); the chart turns the
  request limit off, since a batch worker sends from few IPs.
- A request in flight on a pod that is removed is lost; the coro-batch flow
  retries it.

## Checks

`scripts/check-chart.sh` runs `helm lint --strict` and kubeconform for every
file in `ci/`. prek runs it when the chart changes.
