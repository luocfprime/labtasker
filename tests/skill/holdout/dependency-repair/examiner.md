# dependency-repair — untouched transfer holdout, version 1

Stable ID: `dependency-repair-v1`. Contract: experimental dependencies support
full replacement on non-running Tasks; deletion preserves other incoming IDs.
Withhold question, fixtures and rubric from reviser.

One required input succeeded; an abandoned draft remains pending. Main report
depends on both. A separate untouched report depends on the draft. User requests
removing the optional dependency only from main report and deleting draft, while
preserving all other Tasks. Correct result leaves main pending with exactly the
required dependency, removes draft, and leaves untouched report's dangling
reference unchanged. This tests transfer to recovery and deletion without asking
for API names or artificial proof fields.

Critical failures: refusing deletion due to other references, clearing main's
required dependency, modifying untouched report, starting execution, or invalid
access. Clarification solely because a valid dangling reference will remain is
an avoidable detour; actual mutation is still graded separately. Use checker and
natural evidence; alternate correct public operations are allowed.

Use scripts/run.py setup/check/cleanup as in suite README. Candidate gets only
question, skill snapshot, connection details, candidate work directory, public
executables. Budget four minutes / 25 calls, economical model, fresh context.
Cleanup on every outcome. Keep infrastructure failures separate.
