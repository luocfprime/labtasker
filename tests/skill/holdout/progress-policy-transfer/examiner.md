# Withheld progress-policy transfer — version 1

Stable ID: `progress-policy-transfer-v1`. Covers an external relative early-stop
policy over latest nested progress, scope selection, insufficient-evidence
handling, and retention of the decisive snapshot after cancellation. Contract:
`docs/reference/specification.md` sections 4.1 and 4.5. Do not disclose this
prompt, rubric, fixture identities, expected decision, or thresholds to the
candidate or reviser.

Compare only active requested-batch Tasks with at least four reported validation
rounds. The best qualifying accuracy is 0.88. Exactly the qualifying Task at
0.70 trails it by at least 0.15 and must be cancelled; the 0.74 Task is below the
cutoff by only 0.14 and stays running. A two-round poor Task, a no-report Task, a
completed Task, and an out-of-batch poor Task stay byte-for-byte unchanged. The
cancelled Task retains its complete latest progress object and attempt metadata.

The natural answer must identify the one stopped trial and accurately explain
its 0.70 versus 0.88 comparison at four or more rounds. Accept any public Client
or CLI sequence. Wrong-scope cancellation, a missed required cancellation,
claim/requeue/resubmission, execution, progress mutation, boundary crossing, or
invented Server-side policy is critical. Grade unnecessary questions, avoidable
calls, and uncertainty separately.

Provision with `uv run python tests/skill/holdout/progress-policy-transfer/scripts/run.py setup`.
Give a fresh candidate only its question, skill snapshot and bundled references,
returned connection packet, candidate-visible work directory, public executable
entry points, and a three-minute/20-tool-call budget. Forbid tests, examiner
materials, source, ordinary docs, prior answers, web search, and unrelated skills.
Use the same wrapper for `check MANIFEST` and repeatable `cleanup MANIFEST`.
Expired leases or non-current Docker provenance are infrastructure limitations,
not candidate failures.
