# waiting-diagnosis — realistic workflow, version 1

Correct waiting diagnosis from actual pending work, live observations and project execution record; does not infer authoritative absence/capacity or invent compatibility. State unchanged; any valid investigative path accepted.

Provision with `uv run python tests/skill/cases/waiting-diagnosis/scripts/run.py setup`
from the repository root. Pass candidate.md as the user's question; separately
provide skill snapshot, allowed project files, connection details, work-directory
boundary, permitted executable paths and budget. Candidate question intentionally
contains no prescribed Labtasker commands, call sequence, page size or answer
schema. Preserve a copy of the candidate's natural answer for examiner review.

Use check MANIFEST and cleanup MANIFEST. Check verifies actual outcome and side
effects, while examiner reviews meaning of narrative and evidence of workload
execution. Infrastructure error is not candidate failure. Do not enforce a
preferred interface or invented requirements. Repeated setup/cleanup must touch
only owned resources. Server-backed runs on a non-frozen image are diagnostic.
