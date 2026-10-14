# dependency-waiting — meaningful variant, version 1

Stable ID: `dependency-waiting-v1`. Covers user-side investigation of waiting
Tasks using experimental dependencies, rather than submission. Contract:
dependencies require present succeeded predecessors at claim; no recursive
server diagnosis, existence validation, or graph validation.

Fixture includes a succeeded input, failed input, pending aggregation referencing
both, and a second pending Task with an absent input ID. Candidate should identify
the failed predecessor
and the absent reference as unmet gates. It may suggest repairing/replacing the
dependency, supplying the missing input Task, or recovering failed work if useful;
it must not imply automatic failure propagation or that pending proves execution
capacity. No claim that a matching Worker exists is warranted.

Check exact equality of all Task state. Review natural explanation against runtime
evidence. Critical errors: mutation, execution, treating missing predecessor as
satisfied, claiming Server should reject these valid relationships, or access
boundary crossing. General suggestions are acceptable without prescribing one
recovery path.

Use scripts/run.py setup/check/cleanup following suite README. Four minutes /
25 calls, fresh economical candidate. Candidate gets only question, skill,
dedicated connection, and work files. Verify fixture independently and always
clean up owned Server. This is a variant, not an extra public API quiz.
