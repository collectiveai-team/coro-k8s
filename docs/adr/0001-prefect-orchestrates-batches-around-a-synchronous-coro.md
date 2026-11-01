# Prefect Orchestrates Batches Around a Synchronous coro

## Status

Accepted.

## Context

coro is a synchronous HTTP server: the response comes back on the connection
that sent the audio. It has no job store, it refuses Deepgram's `callback`
parameter because it has no durable delivery (coro ADR 0015), and it rejects
work past its ASR queue with 429 and `Retry-After`. The workload here is
offline batches whose results go to a system that receives callbacks.

## Decision

- coro stays as it is: a stateless Deployment, scaled by replicas
  (`charts/coro`).
- A Prefect flow (`coro_batch`) owns the job: it fetches the audio, calls the
  coro Service inside the cluster, stores the transcript, and POSTs a signed
  callback. Prefect keeps the state and the history of each flow run.
- The steps of a job, their order and their retries live in
  `coro_batch/core/jobs.py`, against ports, and are tested with in-memory
  adapters. The flow builds the adapters and runs jobs; it holds no rule.
- Retries honour `Retry-After` and give up after `max_attempts`. A failed job
  is reported like a succeeded one; only an undeliverable callback fails the
  flow run.
- A Prefect global concurrency limit around each transcription caps the
  requests of all flow runs against coro. `parallel_jobs` caps the downloads of
  one flow run.
- Audio and transcripts are reached through fsspec, so one adapter covers S3,
  GCS, HTTP and local files.

## Consequences

- No change to coro is needed. `GET /metrics`, from coro 1.7.0, enables the
  KEDA autoscaling of the chart.
- Callbacks are at-least-once: a receiver deduplicates on `job_id`.
- A coro pod removed mid-request loses the request; the flow retries it on
  another replica.
- Prefect adds a server, a database and a worker to operate.

## Alternatives Considered

- **Callbacks and a job store inside coro.** Rejected for now: it turns a
  stateless server into a stateful one and amends coro ADR 0015 for a need
  that an orchestrator outside covers.
- **One `coro run` pod per job.** Rejected: every job would pay the model load
  and warmup.
- **A plain queue (Celery, RQ, arq) or a KEDA ScaledJob.** Lighter, but without
  the run history, the UI and the scheduling that Prefect gives; it remains an
  option if Prefect proves too heavy to operate.
- **Prefect task retries instead of retries in the job.** Rejected: Prefect
  retries a whole task with a fixed delay, cannot honour `Retry-After`, and the
  job could not report its own final failure to the callback.
