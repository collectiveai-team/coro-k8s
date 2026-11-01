#!/usr/bin/env sh
# Register the flow on the kind cluster and run a batch of three jobs against coro.
#
# Run after examples/kind/up.sh, from the root of the repository. Exits non-zero
# unless the receiver got the three expected callbacks, signed.
set -eu

BATCH_IMAGE="${BATCH_IMAGE:-coro-batch:dev}"
CALLBACK_KEY="${CALLBACK_KEY:-demo-key}"

kubectl --namespace prefect port-forward service/prefect-server 4200:4200 >/dev/null 2>&1 &
FORWARD=$!
trap 'kill $FORWARD' EXIT
export PREFECT_API_URL=http://localhost:4200/api
until curl -fsS "$PREFECT_API_URL/health" >/dev/null 2>&1; do sleep 1; done

# The global limit sized for the coro of the example: 1 replica x 2 permits.
uv run prefect gcl create coro-transcriptions --limit 2 2>/dev/null \
    || uv run prefect gcl update coro-transcriptions --limit 2
uv run python -c "
from prefect.blocks.system import Secret
Secret(value='$CALLBACK_KEY').save('coro-batch-callback-secret', overwrite=True)
"
CORO_BATCH_IMAGE="$BATCH_IMAGE" CORO_URL=http://coro.coro.svc:8000 \
    uv run prefect --no-prompt deploy --all

AUDIO=http://audio.demo.svc/jfk.wav
HOOK=http://callback-receiver.demo.svc/hook
uv run prefect deployment run transcribe-batch/transcribe-batch --watch --params "{
  \"jobs\": [
    {\"job_id\": \"demo-1\", \"audio_url\": \"$AUDIO\", \"callback_url\": \"$HOOK\"},
    {\"job_id\": \"demo-2\", \"audio_url\": \"$AUDIO\", \"callback_url\": \"$HOOK\", \"language\": \"en\"},
    {\"job_id\": \"demo-missing\", \"audio_url\": \"http://audio.demo.svc/none.wav\", \"callback_url\": \"$HOOK\"}
  ]
}"

echo
echo "== callbacks received"
# The receiver logs each request with its JSON body pretty-printed, one field per line.
LOGS=$(kubectl --namespace demo logs deployment/callback-receiver)
RECEIVED=$(printf '%s\n' "$LOGS" | grep -E '^ *"(job_id|status)":' | tr -d ' ,"' | paste -d ' ' - - | sort -u)
EXPECTED=$(printf '%s\n' \
    "job_id:demo-1 status:succeeded" \
    "job_id:demo-2 status:succeeded" \
    "job_id:demo-missing status:failed")
printf '%s\n' "$RECEIVED"
if [ "$RECEIVED" != "$EXPECTED" ]; then
    echo "FAIL: expected callbacks:" >&2
    printf '%s\n' "$EXPECTED" >&2
    exit 1
fi
if ! printf '%s\n' "$LOGS" | grep -q 'ask not what your country'; then
    echo "FAIL: no callback carried the JFK transcript" >&2
    exit 1
fi
if ! printf '%s\n' "$LOGS" | grep -q '"x-coro-batch-signature": "sha256='; then
    echo "FAIL: the callbacks were not signed" >&2
    exit 1
fi
echo "OK: three callbacks, signed, with the expected outcomes"
