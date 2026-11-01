# coro-k8s

Batch transcription with [coro](https://github.com/collectiveai-team/coro) on
Kubernetes. coro serves transcriptions synchronously; this repository adds what
an offline, callback-driven workload needs around it:

- `charts/coro`: a Helm chart that runs coro as replicas sized by their CPU
  limit, with optional autoscaling on queued ASR work (KEDA) or on CPU (HPA).
- `coro_batch`: a Prefect flow that takes a batch of jobs, fetches each audio
  file, transcribes it with the coro Service, stores the transcript and POSTs a
  signed callback.
- `deploy/prefect`: values for the official `prefect-server` and
  `prefect-worker` charts.
- `examples/kind`: the whole stack on a laptop.

```
caller ──(Prefect API: run transcribe-batch with jobs)──▶ Prefect server
                                                            │
                         Prefect worker ── one Job per flow run (coro-batch image)
                                                            │ fetch audio (fsspec: s3, gs, https, file)
                                                            │ POST /v1/audio/transcriptions ──▶ Service coro ─▶ replicas
                                                            │ store transcript (optional)
caller ◀──────────────(signed POST to callback_url)─────────┘
```

## A job

The flow `transcribe-batch` takes `jobs`, a list of:

| Field | Required | Meaning |
|---|---|---|
| `job_id` | yes | Your identifier; it comes back in the callback. |
| `audio_url` | yes | fsspec URL of the audio: `s3://`, `gs://`, `https://`, `file://`. |
| `output_url` | no | fsspec URL where the coro response is written. Without it, the response travels in the callback. |
| `callback_url` | no | Receives the outcome as a JSON POST. |
| `language`, `prompt` | no | Passed to coro. |
| `response_format` | no | `json`, `verbose_json` (default) or `diarized_json`. |

and `parallel_jobs` (default 8), the jobs of the batch in progress at once.

The callback body is the outcome:

```json
{"job_id": "a-1", "status": "succeeded", "finished_at": "2026-11-01T12:00:00Z",
 "output_url": null, "transcript": "{\"text\": \"...\"}", "error": null, "attempts": 1}
```

With a key configured, `X-Coro-Batch-Timestamp` carries Unix seconds and
`X-Coro-Batch-Signature` carries `sha256=` and the hex HMAC-SHA256 of
`"<timestamp>.<body>"`. A callback can arrive more than once; deduplicate on
`job_id`.

### Failures and retries

- coro answering 429, 502, 503 or 504, a 5xx, or no answer: the transcription is
  retried, after the `Retry-After` coro sends, else after 5, 10, 20... seconds,
  up to `CORO_BATCH_MAX_ATTEMPTS` attempts (default 6).
- coro refusing the request (another 4xx), or audio that cannot be read: the job
  fails at once.
- A failed job is reported to its callback with `status: failed` and `error`.
- A callback that cannot be delivered after the same retries fails the flow run,
  after the other jobs of the batch finish.

### Concurrency

Two bounds apply:

- `parallel_jobs` bounds downloads and requests within one flow run.
- The Prefect global concurrency limit `coro-transcriptions` bounds the
  transcriptions of every flow run together. Size it near `replicas x
  CORO_ASR_MAX_CONCURRENCY` of coro. It must exist before a flow runs:
  `prefect gcl create coro-transcriptions --limit 8`.

## Settings of the flow runs

`CORO_BATCH_*` variables, read by `coro_batch/settings.py`. `prefect.yaml` sets
them as job variables of the deployment.

| Variable | Default | Meaning |
|---|---|---|
| `CORO_BATCH_CORO_URL` | `http://coro:8000` | The coro Service. |
| `CORO_BATCH_CORO_TIMEOUT_SECONDS` | `3600` | Wait for one transcription. |
| `CORO_BATCH_MAX_ATTEMPTS` | `6` | Attempts of each step. |
| `CORO_BATCH_MAX_RETRY_WAIT_SECONDS` | `600` | Longest wait between attempts. |
| `CORO_BATCH_CALLBACK_SECRET` | | HMAC key of the callbacks. |
| `CORO_BATCH_CALLBACK_SECRET_BLOCK` | | Prefect Secret block with the key, when the variable is unset. |
| `CORO_BATCH_CONCURRENCY_LIMIT` | `coro-transcriptions` | Global concurrency limit; empty disables it. |
| `CORO_BATCH_WORK_DIR` | system temp | Where audio is downloaded. |
| `CORO_BATCH_ENV`, `CORO_BATCH_LOG_LEVEL` | `dev`, `INFO` | `prod` logs JSON. |

## Try it on kind

Needs docker, kind, kubectl, helm and uv, about 15 GB of disk for the images,
and network access.

```sh
uv sync
examples/kind/up.sh        # cluster, images, coro (whisper-tiny on CPU), Prefect, demo services
examples/kind/run-demo.sh  # deploys the flow, runs 3 jobs, checks the callbacks
kind delete cluster --name coro-k8s
```

## Deploy

1. coro: `helm install coro charts/coro -n coro --create-namespace -f my-values.yaml`.
   See [charts/coro/README.md](charts/coro/README.md).
2. Prefect: `helm install prefect-server prefect/prefect-server -n prefect -f deploy/prefect/server-values.yaml`
   and `helm install prefect-worker prefect/prefect-worker -n prefect -f deploy/prefect/worker-values.yaml`.
3. The flow image: `ghcr.io/collectiveai-team/coro-batch`, built from the
   `Dockerfile` by `.github/workflows/docker.yml`.
4. The limit, the key and the deployment, against the Prefect API:

   ```sh
   prefect gcl create coro-transcriptions --limit 8
   python -c "from prefect.blocks.system import Secret; Secret(value='...').save('coro-batch-callback-secret')"
   CORO_BATCH_IMAGE=ghcr.io/collectiveai-team/coro-batch:0.1.0 \
   CORO_URL=http://coro.coro.svc:8000 prefect deploy --all
   ```

5. Start a batch with `POST /api/deployments/{id}/create_flow_run` and
   `{"parameters": {"jobs": [...]}}`, or `prefect deployment run`.

## Development

```sh
uv sync
uvx prek install
uvx prek run --all-files      # ruff, pyrefly, botica, helm lint + kubeconform
uv run pytest                 # tests/entrypoints starts a temporary Prefect server
```

`.github/workflows/e2e.yml` runs `examples/kind/up.sh` and `run-demo.sh` on a
kind cluster in CI: on pull requests that touch the chart, the flow, the
Prefect files or the image, every night, and on demand. It takes about 15
minutes.

Decisions are recorded under [docs/adr](docs/adr).
