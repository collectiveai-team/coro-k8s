# coro-k8s

Batch transcription with coro on Kubernetes: the Helm chart of coro (`charts/coro`) and a Prefect
flow (`coro_batch`) that fetches audio, transcribes it with the coro Service, stores the result and
calls back. README.md describes the layout; decisions live in `docs/adr/`.

## Dev Workflow

```sh
uv sync                         # dependencies, from uv.lock
uvx prek run --all-files        # ruff, pyrefly, deptry, botica, helm lint + kubeconform
uv run pytest                   # tests/entrypoints starts a temporary Prefect server
scripts/check-chart.sh          # the chart checks alone (helm on PATH, Docker)
```

- `coro_batch` layers, top down: `entrypoints` (Prefect flows, wiring), `impl` (adapters),
  `core` (models, ports, the steps of a job), `settings`. `botica.toml` enforces them.
- Tests drive `core` through the in-memory adapters of `tests/support/fakes.py`; the adapters of
  `impl` are tested against in-process transports (`httpx.MockTransport`, fsspec `memory://`).
- A change to the chart adds or updates a values file under `charts/coro/ci/` when it adds a
  configuration that no file renders.
- Versioning is tag-driven (hatch-vcs). A tag `vX.Y.Z` publishes `ghcr.io/collectiveai-team/coro-batch:X.Y.Z`.

## Repo Workspace Defaults

- Use `.scratch/` for temporary plans, issue drafts, and disposable notes.
- Use `.tmp/` for generated local artifacts that should not be committed.
- Use `.worktrees/` for local Git worktrees when needed.
- Use `.journals/` for local/private session journals when using the `journalist` skill.
- Preserve unrelated user changes and avoid destructive Git commands unless explicitly requested.

### Resource Limits For Heavy Commands

Run computationally expensive commands (heavy builds, full test suites, data jobs, memory-hungry tooling) under `systemd-run` so a runaway process cannot exhaust the machine:

- Cap memory with `MemoryMax` (hard limit; process is killed if exceeded) and disable swap thrashing with `MemorySwapMax=0`.
- Cap CPU with `CPUQuota` (e.g. `400%` = up to 4 cores).
- Use a transient user scope (no root needed). If `systemd-run` is unavailable, fall back to `ulimit -v` for a memory cap.

Measure and log wall time and peak memory with `/usr/bin/time -v`, appending to `.tmp/logs/<command>/<date>_wall-stats.log`. The latest log gives the limits of the next run:

```bash
cmd=build; ts=$(date +%Y-%m-%dT%H-%M-%S)
log=.tmp/logs/$cmd/${ts}_wall-stats.log; mkdir -p ".tmp/logs/$cmd"
systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0 -p CPUQuota=400% \
  /usr/bin/time -v -o "$log" <command>
```

Run long commands in the background with a saved PID so they are not tied to the agent tool timeout, and delegate polling to a monitor sub-agent on a cheap model that runs a `while kill -0 <pid>; do sleep <n>; done` loop and reports only the final exit status, output tail, and stats log path.

```bash
( systemd-run --user --scope -p MemoryMax=4G -p CPUQuota=400% \
    /usr/bin/time -v -o "$log" <command> ) >".tmp/logs/$cmd/${ts}.out" 2>&1 &
echo $! > ".tmp/logs/$cmd/${ts}.pid"
```

A script of the project emits periodic progress to the output log (current step, counts, percent, or heartbeat with a timestamp) so the monitor can tell what they are doing. Flush each line (e.g. Python `print(..., flush=True)` or `PYTHONUNBUFFERED=1`) so progress appears live. The monitor always `tail`s the latest lines of the `.out` log and does not read the full log.

A step that keeps exceeding its limits is reported, with the stats log that shows it.

## Botica rules

Before writing code that a rule covers, run `uvx botica explain <slug>` and
`uvx botica refs show <slug>`. The judgment rules of this repository:

<!-- botica:rules -->
### architecture

- BTARCH002 `separate-orchestration`: A function either orders the steps of a task or carries out one of them. → https://collectiveai-team.github.io/botica/rules/architecture/btarch002-separate-orchestration/
- BTARCH003 `architecture-vocabulary`: Layers and packages are named `entrypoints`, `api`, `database`, `impl` and `core`, an interface is a port and its implementation an adapter, and a concept that already has a name gets no synonym. → https://collectiveai-team.github.io/botica/rules/architecture/btarch003-architecture-vocabulary/

### process

- BTPROC001 `pr-small-by-intent`: A pull request carries one intent, which one sentence with no "and" states. → https://collectiveai-team.github.io/botica/rules/process/btproc001-pr-small-by-intent/
- BTPROC002 `respect-local-repo`: A change keeps the existing, deliberate choices of the repository: its version pins, the configuration of its tools, its dependencies and its layout. → https://collectiveai-team.github.io/botica/rules/process/btproc002-respect-local-repo/

### testing

- BTTEST001 `test-in-memory-adapters`: Tests drive the logic through in-memory adapters of the ports of the project: working fakes that implement the same interface as the production adapter. → https://collectiveai-team.github.io/botica/rules/testing/bttest001-test-in-memory-adapters/
- BTTEST002 `test-through-interface`: Tests call the unit under test through the public interface that production code calls, and assert on observable behaviour. → https://collectiveai-team.github.io/botica/rules/testing/bttest002-test-through-interface/
- BTTEST003 `test-coverage-gap`: A change closes a coverage gap with a test that asserts a behaviour, or by deleting dead code. → https://collectiveai-team.github.io/botica/rules/testing/bttest003-test-coverage-gap/
- BTTEST006 `coverage-exclusion-reachable`: A change leaves out of coverage only code that no test can reach. → https://collectiveai-team.github.io/botica/rules/testing/bttest006-coverage-exclusion-reachable/

### writing

- BTWRIT001 `plain-writing`: Prose says what a thing is and what it does, in plain sentences that a file, a command or an issue of the repository backs, with no inflated words, hedges, trailing judgments, bold emphasis or claims without a source. → https://collectiveai-team.github.io/botica/rules/writing/btwrit001-plain-writing/
- BTWRIT002 `minimal-comments`: A comment says only what the code cannot say through its names and its structure: the reason for a choice that looks wrong, an invariant, a workaround with the link to its cause, or the docstring of a public interface. → https://collectiveai-team.github.io/botica/rules/writing/btwrit002-minimal-comments/
- BTWRIT003 `ubiquitous-language`: Each concept of the domain has one term, the one that `GLOSSARY.md` defines, in the code and in the documentation. → https://collectiveai-team.github.io/botica/rules/writing/btwrit003-ubiquitous-language/

<!-- /botica:rules -->
