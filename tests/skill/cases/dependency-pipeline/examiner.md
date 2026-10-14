# dependency-pipeline — affected workflow, version 1

Stable ID: `dependency-pipeline-v1`. Covers experimental control dependencies
through a real static experiment submission. Contract: specification Task
dependencies and idempotent submission; no result injection or Workflow entity.

Setup writes a candidate-visible pipeline manifest and approved route records.
Accept any public Python/CLI implementation. Check exactly one preparation,
three evaluations, and one aggregation, all pending; arguments/routes match the
manifest; evaluations depend on preparation; aggregation depends on all three
evaluations. The user's submission script must survive a second invocation
without changing the Task set (examiner runs the candidate's documented invocation
before checking). Candidate may choose IDs and script layout.

Critical errors: missing/extra work, execution, dependencies encoded only in args,
invented server-side result injection, or access-boundary violations. Inspect the
normal final answer and actual scripts as well as the state checker. Do not
require a particular API, command, node naming convention, or output format.

Run `uv run python tests/skill/cases/dependency-pipeline/scripts/run.py setup`,
then `check MANIFEST` and `cleanup MANIFEST`. Follow the root suite's dedicated
Server and access packet instructions. Candidate budget: four minutes / 25 tool
calls, economical model, fresh context. Supply only skill snapshot, user request,
work directory, connection details and public executables. Cleanup after every
attempt; infrastructure errors do not count as candidate failures.
