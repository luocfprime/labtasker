---
name: documentation
description: Write or revise Labtasker's README and user documentation, especially product positioning, tutorials, guides, examples, case studies, and navigation. Preserve the project's direct, plain-English style for ML researchers, agent-friendly workflow, and contract accuracy. Do not use for code-only work; pair observable behavior changes with the public-contract-change skill.
---

# Write Labtasker documentation

Write for an ML researcher or engineer who has independent inference,
evaluation, or experiment jobs but has never used Labtasker. The reader may not
know task-queue terminology. Help them understand what Labtasker is within one
sentence, recognize its main benefits within one short section, and decide
whether to use it before teaching the internal model.

## Put definition and value first

The README and documentation homepage should follow this reader journey:

1. One direct sentence defining Labtasker.
2. Prominent links to the documentation, `llms.txt`, and source code.
3. A short paragraph explaining what Labtasker adds to existing ML code.
4. Three to five consolidated key features.
5. Installation and a short representative example.
6. Separate `When to use Labtasker` and `When NOT to use Labtasker` sections.
7. Navigation to tutorials, concepts, guides, and reference pages.

Do not begin with a long hypothetical workload, implementation details, v1
history, or internal terminology. Put fuller motivation and v1-to-v2 rationale
in `docs/why-labtasker.md`.

Keep the README and documentation homepage aligned on the definition, features,
and product boundary. The README may contain a compact example; the homepage
should focus on navigation after establishing the product.

## Write features as claims with evidence

Use the SQLModel-style pattern `**Short benefit:** Concrete explanation.` A
positive adjective such as `effortless` is useful when the following sentence
immediately demonstrates why it is true.

Consolidate related capabilities instead of listing every mechanism separately.
The current product story fits four groups:

- effortless and flexible parallelism;
- resumable and failure-resistant experiments, supported by tested lifecycle
  behavior;
- structured Task records for inspection; and
- easy adoption and use, including end-to-end operation by agents.

Prefer user-visible capabilities such as automatic retry, dynamic priority,
cancellation, recorded results, and agent operation. Do not lead with SQLite,
local daemon startup, dependency separation, leases, or `run_id` fencing. Those
details belong where readers configure or verify the behavior.

Do not narrow the entire product to one incidental condition such as uneven
runtimes or one benchmark type. Concrete scenarios are useful examples, not the
definition of Labtasker's scope.

## Use direct, natural language

Use short sentences that say what the reader can do. Prefer familiar ML words
such as `jobs`, `cases`, `GPUs`, `failures`, `results`, and `restart` before
introducing Task, Worker, Queue, route, attempt, lease, or `run_id`.

Avoid infrastructure metaphors and compressed abstractions on landing pages:

- Write “resume after an interruption without rerunning completed jobs,” not
  “jobs survive interruption.”
- Write “when a Worker stops responding,” not “abandoned Tasks.”
- Write “matching Task,” not “eligible Task,” until matching rules are taught.
- Write “results from old runs,” not “stale results,” until `run_id` is taught.
- Write “a simple loop can be sufficient,” not “a simple loop is better.”

Avoid vague words such as `consistent`, `robust`, `advanced`, `powerful`, or
`easy` unless the same item gives a concrete reason. Do not use em dashes; split
the thought into shorter sentences or use commas, parentheses, or a colon.

Prefer plain English over idioms, metaphors, and colloquial shortcuts. Write
“this example uses addition to demonstrate the workflow,” not “addition stands
in for inference.” Write “Workers take Tasks from the same Queue,” not “Workers
draw from the backlog.” A reader should not need to interpret a turn of phrase
before understanding the product behavior.

Use Labtasker terminology consistently and capitalize public concepts: Task,
Queue, Worker, Client, and Server. Use lowercase `route` because it is a label,
not a resource record.

### Wording blacklist

Never use these phrases or close variants in user-facing documentation:

- `provide the compute`, `supplies the compute`, or `compute you control`.

These phrases sound like infrastructure-provider language and obscure the
actual product boundary. When that boundary matters, state the concrete fact,
such as “Labtasker does not allocate GPUs or start machines” or “You start the
Worker processes.” Do not replace a blacklisted phrase with a synonym that has
the same problem.

Before handing off a documentation change, search every changed user-facing
file for the listed phrases and read the changed prose once for close variants.
Rewrite every match in terms of the specific action or boundary that matters.

Treat explicit user feedback as an input to this blacklist. When a user says
they dislike a type of wording and that wording is common enough to recur in
Labtasker documentation, update the blacklist as part of the same task. Record
the general pattern rather than only the sentence that triggered the feedback,
explain why it should be avoided, and give concrete rewriting guidance. Follow
one-off or context-specific wording preferences in the current edit, but do not
turn them into a repository-wide rule unless they describe a recurring pattern.

## Explain why before how

Navigation and page order should let readers decide whether Labtasker applies
before asking them to learn its model. Put `Why Labtasker?` before `How
Labtasker works`.

Use one primary Diataxis type per page:

- tutorials lead the reader through a complete successful workflow;
- guides solve one concrete task;
- concepts explain the model and design decisions;
- references state exact interfaces and constraints with minimal prose.

Do not create a top-level navigation group for one page. Do not expose internal
concepts as unexplained top-level categories. Worker pages belong with guides;
a single development page should be linked directly.

## Make tutorials demonstrate the queue

A first tutorial should submit multiple cases to one Queue, run them through a
Worker, and verify all recorded results. A single case does not demonstrate why
a queue is useful.

Keep the first tutorial copyable and dependency-free. Use a small evaluation
program that resembles an ML workflow, then link to representative inference or
benchmark examples. State prerequisites before commands and make successful
output recognizable.

When a tutorial first introduces a route, choose a label that looks like the
workload or compatible implementation, such as `robotwin`, `libero`, or
`sdxl-diffusers`. The submitted Tasks and Worker must use the same route.

Keep maintained examples in concise source files and include them with `--8<--`
when the same example is tested. Do not display an entire long implementation
when a short excerpt proves the point.

Comment only the parts of an example that the reader must replace or understand
to adapt it. Do not add comments that restate every line. When real model
loading, inference, evaluation, or project configuration is intentionally
omitted, mark that location explicitly with a short `# TODO: Replace ...`
comment. Fully runnable tutorial code should not contain placeholder TODOs.

## Describe product boundaries explicitly

Use separate `When to use Labtasker` and `When NOT to use Labtasker` sections.
Acknowledge that a simple loop can be sufficient for a small experiment with a
few short jobs that can be rerun in full.

State the boundaries through alternatives:

- use a workflow or DAG system when jobs depend on earlier outputs;
- use a cluster or resource scheduler to allocate GPUs or machines;
- use an artifact store for checkpoints, media, and other large outputs.

Labtasker schedules independent Tasks. Users provide and start the processes
that run them. Keep this boundary visible without interrupting the opening with
implementation responsibility.

## Explain the agent advantage precisely

Labtasker's API, non-interactive CLI, bundled Agent Skill, `llms.txt`, and raw
Markdown documentation allow Labtasker operations to be handed to an agent end
to end. Describe concrete operations: Worker setup, submission, inspection,
priority changes, cancellation, and recovery.

Do not imply that the agent defines the experiment, allocates hardware, or must
remain online while a Worker executes a Task. The researcher still defines the
experiment, and Labtasker does not allocate hardware.

Keep `docs/llms.txt` as a concise, curated map. Put `Why Labtasker?` before the
core model and update the map when a primary entry point moves or changes role.

## Use Mermaid only when relationships need it

Use Mermaid for a lifecycle, component relationship, or multi-step flow when it
is materially clearer than prose or a small table. Good candidates include:

- Client, Server, Queue, and Worker relationships;
- Task state transitions;
- claim, heartbeat, retry, and recovery sequences; and
- choosing between Python, command, and distributed Workers.

Do not add a diagram for a single fact, a short list, or a linear procedure that
is already clear. Keep node labels short, use public terminology, and introduce
the diagram with enough prose for the surrounding section to remain useful when
retrieved without the image. Prefer Mermaid over a new bitmap for maintainable
technical diagrams.

## Use comparisons and case studies selectively

Do not put a without/with comparison table on the landing page by default. Use
one only when it adds information beyond the feature list, normally in `Why
Labtasker?`.

A comparison must explain both method and consequence. Do not write a bare pair
such as “static assignment / dynamic claiming.” Explain what the researcher
does, where it becomes costly, what Labtasker changes, and why that matters.

Use representative case studies such as AIGC generation, ablations, or
Embodied-AI evaluation. A case study should identify the original workload,
show the coordination code the project owned, map each independent case to a
Task, and state what remains outside Labtasker. Treat external projects
respectfully and link important claims to stable primary sources.

## Describe v2 as a design change

When comparing v1 and v2, discuss product decisions rather than renamed flags:

- one complete way to perform each operation;
- explicit route matching;
- defined lifecycle, recovery, and `run_id` protection;
- deterministic interfaces for humans and agents;
- a Python-native local experience; and
- explicit HTTP deployment only when machines share work.

Do not make v1 implementation differences primary product features. Do not
frame extensibility itself as a mistake.

## Control length and verify claims

Give each section one job. Remove repeated motivation, technical qualifications,
and examples that do not change a decision or prevent an error. Prefer a short
paragraph, a compact table, or a small code excerpt over all three.

Before handoff, check every new claim:

1. Verify Labtasker behavior against `docs/reference/specification.md`, code,
   configuration, and tests.
2. Verify external claims against stable primary sources.
3. Remove facts that are accurate but distract from the user's decision or task.
4. Read the result as a new ML researcher and replace technical shorthand with
   direct outcomes.
5. Confirm that a quoted section contains enough context for agent retrieval.
6. Check every changed user-facing file against the wording blacklist and
   rewrite exact matches or close variants.

If observable behavior changes, also use the `public-contract-change` skill and
update the complete public slice. Preserve unrelated worktree changes and never
hand-edit generated `site/`.

For ambiguous positioning or structure work, discuss two to five high-leverage
questions per round. Once the direction is clear, update all affected surfaces,
run `uv run zensical build --clean`, check links, and run examples or focused
tests that support new claims. Documentation-only changes do not require
unrelated runtime tests.
