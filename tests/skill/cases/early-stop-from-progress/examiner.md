# early-stop-from-progress — affected workflow, version 1

Stable ID: `early-stop-from-progress-v1`. Covers inspection of Server-owned
latest progress and an external, user-specified early-stop decision. Contract:
`docs/reference/specification.md` sections 4.1 and 4.5.

The disposable Queue contains running trials in the requested batch at different
checkpoints, a running trial with no report, completed work, and a qualifying
trial in another batch. Exactly `orchid-beta` meets both stated thresholds. The
candidate must cancel it, preserve its latest snapshot, and leave every other
Task unchanged. Its natural answer must identify the stopped trial and accurately
report the decisive snapshot (`step` 1200 and `best_val_loss` 0.97); an ID may be
included but is not required. Accept any public Client or CLI approach.

Critical failures are cancelling another Task, failing to cancel `orchid-beta`,
claiming or executing work, requeueing/resubmitting, changing Task data or
progress, treating the unrelated batch as in scope, or crossing the candidate
access boundary. Sensible listing, filtering, direct gets, and post-action
verification are not detours. Grade narrative accuracy, unnecessary questions,
avoidable calls, and remaining uncertainty separately from the executable state
check.

Provision from the repository root with:

```bash
uv run python tests/skill/cases/early-stop-from-progress/scripts/run.py setup
```

Give a fresh candidate only `candidate.md`, a snapshot of the public skill and
its bundled references, the returned connection details, the candidate-visible
work directory, permitted public executables, and a three-minute/20-tool-call
budget. Explicitly forbid repository source, ordinary docs, tests, examiner
files, prior answers, web search, and unrelated skills. Preserve its trace and
natural answer. The five-minute Task leases make an attempt exceeding the stated
budget an invalid/unexecuted fixture run rather than evidence about the skill.

Run `check MANIFEST` and `cleanup MANIFEST` with the same wrapper. Check verifies
actual Task state, retained progress, and absence of other changes. Cleanup is
repeatable and owns only the disposable Server resources. Infrastructure failure
or an expired lease is not a candidate failure. A macOS run is release evidence
only when the dedicated Docker image was freshly built from the current source.
