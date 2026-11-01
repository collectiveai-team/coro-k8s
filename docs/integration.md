# Integrate an application

An application sends audio to coro-k8s through the Prefect API and gets the
results back as HTTP callbacks. Only the flow runs call coro.

```
your app ──POST create_flow_run──▶ prefect-server ──▶ worker ──▶ Kubernetes Job (coro-batch image)
                                                                  │ fetch audio, transcribe with coro
your app ◀──────────── signed POST to callback_url ───────────────┘
```

Each request starts one flow run of the deployment
`transcribe-batch/transcribe-batch`. The flow run is one Kubernetes Job that
processes every job of its batch. The fields of a job and of the callback are
in the [README](../README.md#a-job).

## Start a batch

### Over HTTP

Any language can do it with two requests against the Prefect API
(`PREFECT_API_URL`, for example `http://prefect-server.prefect.svc:4200/api`
inside the cluster).

```sh
# The deployment id. It changes only when the deployment is recreated; cache it.
DEPLOYMENT_ID=$(curl -fsS "$PREFECT_API_URL/deployments/name/transcribe-batch/transcribe-batch" | jq -r .id)

curl -fsS -X POST "$PREFECT_API_URL/deployments/$DEPLOYMENT_ID/create_flow_run" \
  -H 'Content-Type: application/json' \
  -d '{"parameters": {"jobs": [
        {"job_id": "case-123", "audio_url": "s3://bucket/audio/123.wav",
         "callback_url": "https://your-app.example/hooks/coro", "language": "es"},
        {"job_id": "case-124", "audio_url": "s3://bucket/audio/124.wav",
         "callback_url": "https://your-app.example/hooks/coro", "language": "es"}
      ]}}'
```

The response is the flow run. Keep its `id` to follow the batch. Its
`state.type` is `SCHEDULED`.

Prefect checks the parameters against the schema of the flow before it creates
the flow run. A missing `job_id` or an unknown field answers `409` with the
reason in `detail`, and no flow run is created:

```json
{"detail": "Error creating flow run: Validation failed for field 'jobs[0]'. Failure reason: Additional properties are not allowed ('colour' was unexpected)"}
```

### From Python

With the `prefect` package and `PREFECT_API_URL` set:

```python
from prefect.deployments import run_deployment

flow_run = await run_deployment(
    name="transcribe-batch/transcribe-batch",
    parameters={
        "jobs": [
            {
                "job_id": "case-123",
                "audio_url": "s3://bucket/audio/123.wav",
                "callback_url": "https://your-app.example/hooks/coro",
                "language": "es",
            },
        ],
        "parallel_jobs": 8,
    },
    timeout=0,
)
```

`timeout=0` returns as soon as the flow run is created. Without it,
`run_deployment` waits for the flow run to finish.

## Follow a batch

`GET $PREFECT_API_URL/flow_runs/{id}` returns the flow run; `state.type` is its
state.

| `state.type` | Meaning |
|---|---|
| `SCHEDULED`, `PENDING` | Waiting for the worker or for its pod. |
| `RUNNING` | Jobs are in progress. |
| `COMPLETED` | Every job was reported to its callback, or had none. Some jobs can have failed. |
| `FAILED` | At least one callback could not be delivered. The others were. |
| `CRASHED` | The pod of the flow run died. Jobs without a callback yet are lost. |

The state of the flow run says whether the callbacks were delivered. The outcome
of each job is in its callback: a batch with an audio file that does not exist
ends `COMPLETED`, and that job's callback has `status: failed`.

## Receive the callbacks

Each job POSTs one JSON body to its `callback_url`:

```json
{"job_id": "case-123", "status": "succeeded", "finished_at": "2026-11-01T12:00:00Z",
 "output_url": null, "transcript": "{\"text\": \"...\"}", "error": null, "attempts": 1}
```

- `transcript` is the body that coro returned, as a string. Parse it as JSON a
  second time. Its shape depends on `response_format`.
- With `output_url` in the job, `transcript` is `null` and the coro response is
  in that file.
- With `status: failed`, `error` holds the reason, for example
  `FileNotFoundError('http://audio.example/none.wav')`.

### Verify the signature

When the flow has a key (`CORO_BATCH_CALLBACK_SECRET` or the Prefect Secret block
named by `CORO_BATCH_CALLBACK_SECRET_BLOCK`), each callback has two headers:

- `X-Coro-Batch-Timestamp`: Unix seconds.
- `X-Coro-Batch-Signature`: `sha256=` and the hex HMAC-SHA256 of
  `<timestamp>.<body>` with the key.

Compute the HMAC over the bytes of the body as they arrived. A body parsed and
serialized again can have other bytes. Reject a timestamp far from the current
time, so that a captured request cannot be replayed later.

A receiver with FastAPI:

```python
import hashlib
import hmac
import json
import os
import time

from fastapi import FastAPI, HTTPException, Request

KEY = os.environ["CORO_BATCH_CALLBACK_SECRET"].encode()
MAX_AGE_SECONDS = 300

app = FastAPI()
seen: set[str] = set()  # use your database in production


def is_signed(body: bytes, timestamp: str, signature: str) -> bool:
    """Return whether ``signature`` is the HMAC of ``body`` and ``timestamp`` is recent."""
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_AGE_SECONDS:
        return False
    digest = hmac.new(KEY, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)


@app.post("/hooks/coro")
async def coro_callback(request: Request) -> dict[str, str]:
    body = await request.body()
    if not is_signed(
        body,
        request.headers.get("X-Coro-Batch-Timestamp", ""),
        request.headers.get("X-Coro-Batch-Signature", ""),
    ):
        raise HTTPException(status_code=401)
    outcome = json.loads(body)
    if outcome["job_id"] in seen:
        return {"status": "duplicate"}
    seen.add(outcome["job_id"])
    if outcome["status"] == "succeeded" and outcome["transcript"] is not None:
        transcript = json.loads(outcome["transcript"])
        print(outcome["job_id"], transcript["text"])
    else:
        print(outcome["job_id"], outcome["status"], outcome["error"])
    return {"status": "ok"}
```

To check a signature by hand:

```sh
printf '%s.%s' "$TIMESTAMP" "$BODY" | openssl dgst -sha256 -hmac "$KEY" -hex
```

### What to answer

The flow reads the status code of the answer
([`coro_batch/impl/http_callback.py`](../coro_batch/impl/http_callback.py)):

| Answer | What the flow does |
|---|---|
| `2xx` | Delivered. |
| `408`, `429`, `5xx`, no answer within 30 s, connection refused | Retries, up to `CORO_BATCH_MAX_ATTEMPTS` attempts. |
| Any other status, `3xx` included | Gives up on that callback at once. |

A callback that is not delivered makes the flow run end `FAILED` once the other
jobs finish. Answer `2xx` as soon as the outcome is stored, and do slow work
after.

The flow retries a callback whose answer it did not get, so the same `job_id`
can arrive twice. Store outcomes keyed by `job_id` and ignore a repeat.

## Network and access

- The application reaches the Prefect API. Inside the cluster that is the
  Service `prefect-server` on port 4200. Outside, it needs an Ingress or another
  route to it.
- The pods of the flow runs reach every `audio_url`, `output_url` and
  `callback_url`. A `callback_url` is resolved inside the cluster, so a
  cluster-local name such as `http://your-app.your-ns.svc/hooks/coro` works.
- Credentials for `s3://` or `gs://` go in the environment of the flow runs: the
  job variables in [`prefect.yaml`](../prefect.yaml).
- The Prefect server of [`deploy/prefect`](../deploy/prefect) has no
  authentication. Anyone who reaches its API can start flow runs and read their
  parameters. Keep it inside the cluster, put it behind an authenticating
  proxy, or turn on the basic authentication of Prefect: set
  `PREFECT_SERVER_API_AUTH_STRING=user:password` on the server and
  `PREFECT_API_AUTH_STRING` with the same value on the worker and on the
  application.

## How many jobs per batch

Each flow run starts a pod, and the pod starts before the first job does. When
audio files arrive one at a time, gather them for a short while and send them as
one batch. When they arrive already grouped, send each group as one batch.

`parallel_jobs` (default 8) bounds the jobs of one batch in progress at once.
The global concurrency limit `coro-transcriptions` bounds the transcriptions of
all batches together, so several batches at once share coro without
overloading it ([README, Concurrency](../README.md#concurrency)).
