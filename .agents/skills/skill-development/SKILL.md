---
name: skill-development
description: Develop and regression-test Labtasker's public Agent Skill with concise real-user requests, independent examiner and candidate agents, outcome checks, and bounded self-revision. Use when changing skills/labtasker, evaluating its usability, or adding feature workflow coverage; not for product unit/integration tests or ordinary documentation alone.
---

# Skill self-development SOP

Treat the public skill as a versioned interface for agents. Demonstrate that an
agent given only the skill and a realistic request can complete the work through
public interfaces, and that revisions preserve previously working capabilities.
Establish and incrementally improve this regression loop; do not build a general
evaluation framework before concrete tests require it.

The subject is translating a concise user intent into correct operations. Test
whether the agent can submit experiments, understand progress, diagnose waiting
work, select and recover Tasks, configure a connection, or adapt an existing
script. Do not turn product unit/integration tests into assignments for an agent.

If asked only to design or revise this SOP, edit the procedure without starting
an examination. Otherwise follow the workflow below.

## Roles and access instructions

Use separate examiner and candidate subagents. The orchestrator can perform the
revision role. Isolation is instruction-based; no container or filesystem sandbox
is required. Do not describe this as enforced access control.

- **Examiner:** may inspect the repository, specification, implementation, and
  private tests. Prepares scenarios, provisions disposable environments, holds
  rubrics, evaluates evidence, and proposes a diagnosis. Does not edit the skill
  or relax a rubric to make a candidate pass.
- **Candidate:** receives only the target skill and its bundled references, the
  public question, and permitted environment/tool entry points. May inspect
  runtime state and public API/CLI responses and create task-required work files.
  Must not read repository source, ordinary docs, tests, private fixtures,
  rubrics, other agents' work, earlier answers, or grading notes. Must not use
  web search, package-source inspection, or unrelated skills to recover missing
  instructions. Requests clarification instead of crossing the boundary.
- **Reviser:** receives disclosed failures and evidence, checks the public
  contract, and makes general skill improvements. Must not inspect active holdout
  questions or rubrics. Reviews edits and preserves unrelated changes.

Start each candidate attempt with fresh context and no inherited conversation.
Supply explicit allowed paths, tools, endpoints, and forbidden resources in its
instructions. Ask it to report the skill files read, actions taken, and remaining
uncertainty. Invalidate attempts that cross the boundary rather than scoring them
as skill failures. If fresh subagents are unavailable, report the limitation;
do not simulate an independent exam in the reviser's context.

Specify absolute permitted paths for writes. A shell command's working directory
does not change another tool's working directory: relative `apply_patch` paths
can write outside the candidate environment. Restrict writes to shell/Python
commands with explicit work paths, or require absolute allowed patch paths.
Check actual write locations before grading; correct the candidate packet and
start a fresh attempt after a tool-boundary error.

Prefer an available economical candidate model with a modest thinking budget.
Keep its configuration consistent for comparisons and record it; no multi-model
matrix is required. Choose practical time and tool budgets before running.

## Executable scenarios and durable regression

### Write the user request first

Use the shortest prompt that states the user's goal clearly. Include only the
goal, necessary project background, environment entry points, and real
constraints. Supply existing scripts and project records when a user would have
them. Keep access instructions and execution budgets in the evaluation packet,
separate from the user question.

Do not prescribe API names, commands, execution steps, pagination strategy, or
the expected interpretation. Choosing those is what the skill must enable.
Do not request test-only JSON fields, Boolean proof flags, or a particular report
schema. A normal final explanation and task-required artifacts are sufficient;
the examiner records the trace and evaluates them.

For example, ask “How is the current evaluation batch progressing, and why are
some jobs still waiting? Please only inspect it.” Do not append a tutorial telling
the agent to call grouped counts, follow every cursor, or interpret busy Workers.

Put detailed acceptance criteria in `examiner.md`: goal completion, unintended
changes, correct interpretation, necessary versus redundant questions, and
avoidable detours. Every requirement must follow from the request, supplied
context, or public contract. Accept alternative correct approaches; do not
require one API, command sequence, output layout, or intermediate artifact.
Use checks to verify real outcomes, not to reward reproducing an answer key.

### Keep fixtures separate from decisions

Store cases and results outside the public skill installation tree. Reuse an
existing evaluation location; otherwise start a small, versioned directory under
`tests/skill/`, separate from ordinary pytest discovery. Create only the cases and
helpers needed for the current evaluation.

Use two Markdown files plus automation as needed for each case:

```text
tests/skill/cases/<case-name>/
  examiner.md
  candidate.md
  scripts/
```

`examiner.md` contains setup, acceptance criteria, script usage, and cleanup;
`candidate.md` contains the concise user request. Give allowed resources in a
separate environment packet. The candidate must not
read examiner instructions or setup/checking scripts. Explicitly identify any
task-facing helper it may use. Holdout cases use the same structure under
`tests/skill/holdout/`. No `case.yaml` or separate metadata schema is needed.
One script with setup/check/cleanup commands or several focused scripts are both
acceptable. Extract shared helpers only when real cases demonstrate repetition.
Keep evaluation reports, metadata, and raw run artifacts in ignored
`tests/skill/runs/` or a temporary directory. Routine results do not belong in
version control; preserve durable findings as case or skill improvements.

Between the two Markdown files, record:

- Stable ID, covered user workflow, case version, and contract source.
- Candidate-visible request: goal, necessary context, constraints, environment
  entry points. Record the execution budget in the evaluation packet.
- Examiner-only setup and cleanup: initial data, reproducible seeds, relevant
  fault injection, and platform requirements.
- Examiner-only checks: final result, prohibited side effects, required process
  constraints, and critical failures.

Prefer real user operations with observable outcomes over prose-only quizzes.
Retain a capability decision when it is necessary to the user's actual workflow.
Hidden checks evaluate stated requirements or public-contract rules, not secret
preferences. Verify setup and assertions independently before blaming candidates.
Missing infrastructure is an unexecuted test, not a pass or fail.

All examinations must use a temporary test environment created for the run.
Never connect examination operations, checks, or fault injection to production
or the user's existing working environment, even for read-only checks. Creating
a test Queue on a production Server does not meet this requirement. Provision
dedicated Server processes, temporary databases, work directories, and test
credentials where needed. Explicitly configure endpoints and data paths so
inherited settings cannot select an existing Server or local `.labtasker/` state.
Verify the target belongs to the test run before executing the scenario; if that
cannot be established, report a setup error and do not run it.

Automation should establish reproducible initial state and record the resources
it owns. Separate candidate-visible connection details from private checking
data. Check actual state rather than trusting completion claims; when acceptance
depends on execution history, arrange observable evidence before the attempt.
Prefer read-only result checks. Use fault injection only when a realistic user
operation requires it, not to retest the product's low-level mechanisms.
Distinguish pass, candidate failure, infrastructure error, and unexecuted checks.
Cleanup must tolerate repeated calls and partial setup, run after success,
failure, or timeout, and remove only this run's resources. Preserve diagnostic
evidence before cleanup. Let subsequent agents design scripts to meet these
requirements without imposing a framework or fixed script interface in advance.

Maintain three complementary sets:

- **Regression:** stable historical cases, especially prior failures.
- **Variants:** change meaningful user goals, project context, or runtime state to
  test transfer; renaming IDs alone is insufficient.
- **Holdout:** questions and rubrics withheld from candidates and the reviser
  until evaluation. The examiner sends each candidate only its question and sends
  the reviser aggregate results only. If a case must be disclosed for diagnosis,
  retire it into regression and replace it.

Keep test-specific IDs, prompts, fixtures, expected answers, and grading logic out
of the skill. Teaching the general rule needed to solve a test is appropriate;
teaching recognition of that test is leakage. Do not make a failing test easier
without independent evidence that its requirements or checker are wrong.

## Regression and revision loop

1. Inspect the working diff and affected capabilities. Record the skill snapshot,
   software version, case versions, candidate configuration, tool permissions,
   and seeds. Preserve a baseline before revision; when unavailable, explicitly
   limit claims about regression improvement.
2. Select affected cases plus stable core regression. Bootstrap a modest set of
   real workflows if no suite exists. Prepare holdouts before using failures to
   guide revisions; do not block on building a large framework.
3. Have the examiner provision each environment and give a fresh candidate only
   its allowed packet. Capture observable calls, outputs, final state, and the
   candidate's explanation. Do not request hidden chain-of-thought.
4. Grade with executable checks first and examiner judgment where needed. Record
   correctness, side effects, process compliance, avoidable detours, and cost
   separately. Mark results correct, partial, or incorrect and identify critical
   errors explicitly. Sensible inspection and verification are not detours. A
   valid alternative is not incorrect just because its command sequence differs.
5. Diagnose using the table below. Repeat ambiguous cases with fresh candidates
   before changing the skill. Diagnostic attempts given extra guidance cannot
   count as formal passes.
6. For demonstrated skill defects, make the smallest general correction. Re-run
   the failed case, a meaningful variant, and core regression. Compare against
   the baseline under equivalent conditions; distinguish new regressions from
   pre-existing failures and model variability.
7. Run the maintained suite and untouched holdouts for final acceptance. Repeat
   critical or inconsistent cases when needed. Report actual repeated outcomes,
   not just the most favorable run.

| Diagnosis | Action |
| --- | --- |
| Skill omission, ambiguity, wrong instruction, or poor routing | Automatically revise the skill and necessary companion documentation within authorized scope; retest. |
| Implementation contradicts the specification | Reproduce and report the bug; ask the user before changing product code, even when the bug is clear. |
| Product design or public contract cannot meet the intended workflow | Prepare a concrete proposal and obtain user approval before changing design, contract, or implementation. |
| Invalid question, checker, setup, or environment | Correct the test on independent evidence, version the correction, and rerun; invalidate the original score. |
| Model variability or uncertain cause | Gather bounded additional evidence; do not automatically append warnings to the skill. |

For product bugs, provide a minimal reproduction, expected versus observed
behavior, contract evidence, and proposed fix. For design proposals, explain the
unmet workflow, why skill changes are insufficient, the smallest design change,
affected public surfaces, compatibility effects, and the decision needed. Do not
silently teach around product defects. Continue independent skill work while a
product decision is pending, without treating pending cases as passed.

Default to at most three revision rounds per invocation. Stop earlier if the same
failure persists after two targeted corrections, access boundaries cannot be
maintained, or an approved budget is exhausted. Report remaining evidence and the
next decision; never weaken checks to claim convergence.

## New features and process improvement

Derive a feature scenario from the user operation it enables. Extend an existing
workflow when possible, rather than adding a separate question for every method,
flag, validation boundary, or response model. A meaningful variant changes what
the agent must decide, not merely which API it is instructed to call. Include
recovery or a capability boundary when it arises naturally in the user's goal.
Do not require every interface in the agent suite; ordinary automated tests own
HTTP/Python/CLI equivalence and implementation invariants. Validate outcome
checks independently before bringing the scenario into the regression loop.

Improve this SOP or evaluation helpers when repeated evidence demonstrates a
process defect. Keep changes small, explain the evidence, and preserve approval
boundaries, role separation, and anti-leakage rules. SOP changes do not
retroactively turn failed evaluations into passes.

## Acceptance and report

Accept a revision when executed core regression has no critical errors or newly
introduced failures, affected capabilities pass with meaningful variants, and an
untouched holdout reaches at least 90% fully correct with no critical error.
Report counts and case-level failures alongside percentages. Document pre-existing
noncritical misses; do not silently delete or relabel them as out of scope.
Small or incompletely executed suites justify only correspondingly limited claims.

Report scope and versions, before/after results, critical errors, path quality
and cost observations, changes made, unexecuted cases, remaining uncertainty, and
product decisions awaiting approval. Preserve case definitions and compact evidence
so later agents can reproduce failures. Keep raw artifacts out of the public skill.
Do not commit, push, or publish without explicit authorization.

## Labtasker application

- Target `skills/labtasker/`. Use `docs/reference/specification.md` as the contract,
  checked against public interfaces and executable behavior. Record disagreements
  instead of silently teaching either side.
- Start with the maintained suite in `tests/skill/` and its coverage map. Extend
  the relevant cases for a feature instead of creating a second evaluation
  location. Keep private holdout definitions out of reviser reads, including
  shared helper code and broad search output.
- Cover submitting experiments, inspecting progress, diagnosing waiting work,
  filtering and recovering Tasks, configuring connections, and integrating
  existing scripts. Let the agent choose Python or CLI unless the user's project
  imposes a real interface constraint.
- Keep low-level retries, run fencing, strict type boundaries, process-tree
  termination, database locking/migrations, and protocol invariants primarily
  in ordinary automated tests. Do not ask the candidate to prove these mechanisms.
  Relevant safety rules still constrain real operations: for example, recovery
  must preserve completed work, and an unavailable query cannot justify treating
  a Queue as empty. Invented capabilities, damaging mutations, and wrong
  platform/deployment claims remain critical errors.
- Use `uv` from the repository root for evaluation helpers. Platform-specific
  scenarios require a suitable environment; report unavailable coverage.
- Keep the public entry skill short, with product boundaries, the default path,
  and direct links to focused references. Give each rule one natural home.
- Validate skill structure and links. When the public skill or installation
  guidance changes, update `docs/guides/agent-skill.md` as needed and run the
  documentation build. SOP-only edits need structure and consistency checks,
  not unrelated runtime tests or an automatic examination.
