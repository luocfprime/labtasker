# Agent workflow regression

This suite tests whether an agent can use `skills/labtasker/` to turn a concise
user request into correct operations. It does not ask agents to reproduce product
unit or integration tests. Follow `.agents/skills/skill-development/SKILL.md`.
`tests/conftest.py` excludes this directory, including generated candidate work,
from ordinary pytest discovery.

## Cases

| Workflow | User goal | Examiner checks |
| --- | --- | --- |
| submit-sweep | Queue a planned experiment sweep without starting execution | Complete intended experiment set, correct inputs, no duplicate or unrelated work |
| run-existing-evaluator | Integrate an existing evaluator and run the batch with reusable setup | Actual evaluation results, script integration, preserved project behavior |
| progress-summary | Summarize completion and remaining work | Complete, accurate summary; no unintended changes |
| early-stop-from-progress | Apply a supplied early-stop rule to current progress | Latest snapshots inspected, exact running Tasks cancelled, retained diagnostics and unrelated work preserved |
| waiting-diagnosis | Explain why evaluation is waiting and suggest the next action | Evidence supports the diagnosis; uncertainty is preserved; no unauthorized changes |
| recover-selected-batch | Resume failed or cancelled work in one experiment batch | Correct selection and recovery; successful and unrelated work preserved |
| connect-project | Repair the project's connection and run its existing evaluation | Intended endpoint/Queue used, working project configuration, actual result |
| Holdouts | Three withheld user workflows that change the decision context | Independent outcome checks and interpretation review |

`candidate.md` contains only the goal, necessary background, environment entry
points, and real constraints. It does not name an API, command, sequence of
steps, pagination strategy, expected conclusion, or test-only report format.
Existing project scripts and records are supplied when they are part of the
user's context. The agent chooses how to do the work.

`examiner.md` holds setup, detailed acceptance criteria, checks, and cleanup.
Check goal completion, unintended changes, interpretation, unnecessary questions,
and avoidable detours. Requirements must follow from the request, context, or
public contract. Accept different correct approaches and natural final answers;
do not grade conformity to one command sequence or artifact layout.

Low-level retries, run fencing, type validation, process-tree termination, and
database mechanisms remain primarily in ordinary automated tests. The helpers
here provision disposable environments and verify the results of user operations.

## Run an examination

From the repository root:

```bash
uv sync --all-packages --group dev --frozen
uv run python tests/skill/cases/submit-sweep/scripts/run.py setup
```

Use the returned work directory and connection details to prepare a fresh
candidate's environment packet. Give it the case question, a snapshot of the
public skill, and the permitted project files/tools. Keep access rules, absolute
work paths, and a practical time/tool budget separate from the user question.
Do not give it examiner files, fixtures/checkers, repository source/docs, earlier
answers, or grades. Holdout questions and rubrics are withheld from the reviser.
This is instruction-based isolation, not an operating-system sandbox.

Use shell/Python writes with absolute permitted paths. A shell command's workdir
does not change `apply_patch`'s directory; disallow relative patch writes. Check
actual write locations and invalidate boundary crossings. Strip inherited
`LABTASKER_*` settings before applying the dedicated environment's connection.

Save the candidate's normal final answer and execution trace as examiner evidence.
Then use the real manifest path returned by setup:

```bash
uv run python tests/skill/cases/submit-sweep/scripts/run.py check /absolute/run/manifest.json
uv run python tests/skill/cases/submit-sweep/scripts/run.py cleanup /absolute/run/manifest.json
```

A successful checker does not establish complete agent success; review the
answer and trace too. Validate fixtures independently before attributing a
failure to the skill. Record invalid attempts, infrastructure errors, and
unexecuted checks separately from candidate failures.

Cleanup runs after success, failure, timeout, or partial setup and tolerates
repeated calls. Track candidate process/session IDs and stop remaining Workers
before removing the Server. The fixture owns Server resources, not arbitrary
candidate subprocesses. Preserve evidence in ignored `tests/skill/runs/` and
remove only the run's own resources. Never use an existing Server or database.

## Environments and evidence

Linux uses a dedicated foreground Server with a temporary SQLite file and token.
The tested macOS host has an ownership-lock/SQLite startup conflict, so these
HTTP workflows use a dedicated Linux Docker Server there. Build from current
sources and the frozen dependencies:

```bash
docker build -f tests/skill/Dockerfile -t labtasker-skill-current .
```

`LABTASKER_SKILL_IMAGE` selects another image. Keep the database inside the Linux
container, not on a macOS bind mount. Record its digest and installed dependency
versions. A cached image outside the supported dependency requirements provides
diagnostic evidence only. These helpers do not implement Windows-host execution.

Record case versions, skill hashes, software/environment, candidate configuration,
and case-level outcomes with path quality and cost separate from correctness.
Changed user questions require fresh attempts; previous results do not transfer.
The earlier instruction-heavy suite and its results are superseded and must not
be presented as evidence that these user workflows passed. Keep dated reports
and metadata in ignored `runs/reports/`, alongside other run artifacts under
`runs/`. Commit case definitions, checking scripts, and durable regressions learned
from failures; do not commit routine evaluation output. Preserve a concise release
acceptance report in version control only when explicitly needed.
