# archive-completed-batch — realistic workflow, version 1

Contract: specification sections 4.2 and Task archive/update/list interfaces.
Workflow: hide a completed batch without deleting records or affecting execution.

Provision with `uv run python tests/skill/cases/archive-completed-batch/scripts/run.py setup`.
Supply only candidate.md, the Skill snapshot, and the returned environment packet.
Keep this rubric and setup/checking code private. Use check MANIFEST then cleanup
MANIFEST; both reuse the dedicated disposable Server lifecycle in scenario.py.

Seed the selected batch with succeeded, failed, cancelled, pending, and running
Tasks; also seed unselected terminal work and an already archived selected success.
The checker observes all records including archives. Every selected terminal Task
must be archived, no record deleted or executed, and all fields except the effective
archive flag/updated_at preserved. Unfinished and other-batch Tasks are unchanged.
The candidate should explain that the records/results remain retrievable and that
ordinary collection visibility excludes archives. Alternative correct public
interfaces are valid. Check final state first, then independently review the answer
and trace for access compliance and unintended actions.

Infrastructure errors are unexecuted coverage, not candidate failures. Owned
resources and evidence remain in the returned manifest directory after cleanup.
