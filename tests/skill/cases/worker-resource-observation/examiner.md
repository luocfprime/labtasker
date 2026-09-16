# worker-resource-observation — realistic workflow, version 1

Inspect user-defined Worker placement and latest resource telemetry without
mistaking observations for scheduling authority or inventing dynamic grouping.
State must remain unchanged; any correct read-only investigative path is valid.

Provision with
`uv run python tests/skill/cases/worker-resource-observation/scripts/run.py setup`
from the repository root. Give the candidate `candidate.md`, a snapshot of the
public Labtasker skill, `connection.json`, the absolute work directory, permitted
Labtasker/Python executables, and a five-minute budget. Forbid repository source,
ordinary docs, tests, examiner files, web search, and writes outside the work
directory. Preserve the answer and observable command/API trace.

The fixture has three Workers in Queue `default`:

- `w_ResourceA001`: route `llama`, node-a, GPU 0, busy, latest utilization 92%
  and memory 38 GiB. An earlier snapshot also contained temperature; replacement
  means temperature must not appear now.
- `w_ResourceA002`: route `llama`, node-a, GPU 1, idle, utilization 14% and
  memory 6 GiB.
- `w_ResourceB001`: route `bert`, node-b, GPU 0, busy, utilization 77% and
  memory 31 GiB. It must be excluded from the requested node-a result.

Full credit requires selecting exactly the two node-a Workers; reporting Queue,
route and GPU IDs accurately; identifying GPU 0 as busy and GPU 1 as underused;
using only the latest complete telemetry object; and preserving the distinction
between observation and scheduling authority. The candidate may filter
`metadata.*` on the Server or enumerate the small Worker set locally. It must
not attempt grouping by metadata/telemetry, claim work, mutate Tasks, report new
telemetry, withdraw observations, or infer historical samples. Asking no
unnecessary clarification and avoiding irrelevant Task scans count toward path
quality, not basic correctness.

Run `check MANIFEST` after the attempt and always run `cleanup MANIFEST`.
The checker verifies that all Tasks and Worker observations, including telemetry
timestamps and complete objects, remain unchanged. Infrastructure expiry or
setup failure is unexecuted evidence, not a candidate failure.
