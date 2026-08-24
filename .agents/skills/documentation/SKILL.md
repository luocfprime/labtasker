---
name: documentation
description: Write or revise Labtasker's README and user documentation, especially product positioning, motivation, comparisons, case studies, examples, and navigation. Preserve the project's plain-language, agent-friendly style and contract accuracy. Do not use for code-only work; pair public behavior changes with the public-contract-change skill.
---

# Write Labtasker documentation

Write for a capable ML practitioner who knows the frustrations of running
experiments but has never used Labtasker. The reader may not know task-queue
terminology or even recognize the generated shell and Python glue as a “wrapper
script.” Help them decide quickly whether Labtasker solves their problem before
teaching the product model.

## Lead with the problem and outcome

Treat the opening like a paper abstract: state the user problem, the practical
outcome, and the product boundary before installation or architecture.

- Explain the recognizable situation first: many cases, several GPUs, uneven
  runtimes, interruption, failures, changing priorities, and scattered results.
- Acknowledge that a simple script is often the right solution for a few cheap
  jobs that can all be rerun. Explain the point at which it stops being enough;
  do not manufacture a strawman.
- Prefer a concrete setup such as “100 evaluations and 8 GPUs” over an abstract
  list of orchestration concerns.
- Describe Labtasker as the tested coordination layer that replaces repeated
  project-specific task distribution, recovery, and result-collection code.
- Keep the boundary visible: users provide the machines, GPUs, processes, and
  artifact storage. Labtasker schedules independent work; it is not a resource
  allocator, cluster scheduler, DAG engine, or artifact store.

Loading an expensive model once is a useful Worker capability, especially for
inference, but it is not the main motivation or definition of Labtasker.

## Use the reader's language before Labtasker's language

On landing pages, start with `jobs`, `cases`, `GPUs`, `failures`, `results`, and
`restart`. Introduce `Task`, `Worker`, `Queue`, `route`, attempt accounting, and
`run_id` only after the value is clear.

Avoid unexplained phrases such as `ad hoc orchestration`, `durable state`,
`eligible Task`, `shared backlog`, `lifecycle`, or `artifact references` in the
first-screen explanation. State their observable effect instead:

- “Labtasker remembers what finished” before explaining persisted Task state.
- “Continue unfinished jobs without repeating completed work” before retry and
  recovery semantics.
- “An old process cannot overwrite a newer result” before `run_id` fencing.
- “Label which implementations may run a job” before exact route matching.

Use Labtasker terminology consistently and capitalize public concepts—Task,
Queue, Worker, Client, and Server—once they are introduced.

## Make comparisons prove the value

A comparison must explain both the method and its consequence. Do not write a
bare mapping such as “static assignment / dynamic claiming.” Use this shape in
each cell:

```text
What the user normally does. Why it works initially, then where it breaks.
What Labtasker does. Why that makes the workflow easier or safer.
```

The main without/with comparison should cover most user-visible reasons to use
Labtasker, in plain language:

- balancing work when runtimes differ;
- remembering completed work and continuing after interruption;
- tested retries, recovery, and protection against stale processes;
- consistent structured results without log parsing;
- adding, cancelling, or prioritizing work during a run;
- explicit compatibility during implementation rollouts;
- reusing expensive loaded state across jobs; and
- a standardized workflow that an agent can operate.

For the current landing comparison, use the Zensical/GitHub-compatible headings
`Without Labtasker :cry:` and `With Labtasker :smiley:`. Keep the configured
Twemoji SVG extension rather than embedding platform-dependent emoji images.

## Explain the agent advantage precisely

Agent-written scripts do not eliminate orchestration cost. Without a standard
tool, the user must still specify load-balancing heuristics, progress storage,
locking, retry behavior, recovery, and result parsing; the agent then invents and
debugs another lightly tested task system.

Present Labtasker as cleaner, better tested, more reliable, and easier to
automate because its workflow and interfaces are standardized and explicit. The
bundled Agent Skill should make a request such as “run these jobs in parallel
across 8 GPUs with Labtasker” sufficient to begin the ordinary workflow.

Do not claim that an agent “takes care of everything.” The user still defines
the experiment and supplies the hardware; execution remains deterministic after
a Worker starts. The agent handles routine setup, submission, inspection,
updates, and recovery through documented interfaces.

## Use representative case studies

Prefer real experiment shapes over toy infrastructure examples:

- AIGC generation or ablation across prompts, seeds, checkpoints, and settings.
- Embodied-AI evaluation across benchmark suites and subtasks with unequal
  runtimes, where static splitting leaves GPUs idle and scatters results.

A case study should identify the original workload, show the coordination code
the project had to own, map each independent case to Labtasker, and state what
remains outside Labtasker. Treat external projects respectfully: use them as
evidence that reasonable scripts grow scheduling responsibilities, not as bad
code to ridicule. Link to a stable source and do not publish an untested
replacement as a runnable integration.

## Control the reader's workload

Documentation competes with the experiment for the reader's attention. Use the
shortest version that still lets a reader recognize the problem, understand the
outcome, and verify the claim.

- Put the takeaway and the most concrete evidence first. A number such as “50
  benchmark cases” or “a 548-line launcher” is more useful than several
  paragraphs of general setup.
- Give each section one job. Prefer a short paragraph, a compact comparison, or a
  small code excerpt over repeating the same point in all three forms.
- Keep maintained examples in concise source files and include them with
  `--8<--` snippets instead of duplicating code in Markdown. Snippets prevent
  drift; they do not justify displaying an entire long implementation when an
  excerpt proves the point.
- Keep landing-page examples brief and link to a focused page for detail. Do not
  duplicate the full motivation across README, the documentation index, and a
  case study.
- In a case study, explain only enough of the external domain and codebase to
  understand the scheduling problem. Link to upstream setup and implementation
  details instead of retelling them.
- After drafting, make a compression pass. Remove background, qualifications,
  terminology, and examples that do not change whether the reader would use
  Labtasker or how they understand its boundary.

Longer is justified only when the extra detail answers a likely decision or
prevents a materially wrong implementation.

## Fact-check before handoff

Audit every new positioning, comparison, and case-study claim at three levels:

1. **Is it true?** Check the current specification and implementation for
   Labtasker claims. For external projects, use primary sources and stable commit
   links; verify counts, commands, task granularity, and behavior directly. Mark
   historical prototypes as historical, distinguish inference from documented
   behavior, and state when compared implementations do not have feature parity.
2. **Is it the point?** Keep facts that demonstrate the user's problem, the
   practical outcome, or Labtasker's boundary. Omit accurate but distracting
   implementation trivia.
3. **Is it compelling?** Make the first screen answer why the reader should care.
   Prefer a representative workload, a concrete cost, and a visible before/after
   consequence over generic praise.

For a case study, keep a small evidence ledger while writing: the claim, its
primary source, and the exact commit or version checked. The ledger need not be
published, but every important external claim should link to a stable source in
the finished page. Re-read the result as a skeptical ML practitioner and remove
any claim that is technically defensible but misleading in emphasis.

## Describe v2 as a design change

When comparing v1 and v2, discuss core design decisions rather than a changelog
of renamed flags:

- one obvious, complete way instead of overlapping shortcuts and implicit
  interactions;
- explicit route matching instead of inferring consumption from Task arguments;
- defined lifecycle, recovery, and `run_id` fencing;
- deterministic, non-interactive interfaces designed for agents and automation;
- a Python-native local experience backed by SQLite rather than requiring
  MongoDB or using Mongomock as an embedded substitute; and
- one-install, minimal-configuration local use with explicit HTTP deployment
  only when machines need to share work.

Do not frame extensibility or plugins as mistakes. The problem is incomplete or
ambiguous built-in behavior, not extension itself.

## Keep surfaces and claims aligned

- Keep the README and documentation landing page aligned on positioning and the
  main comparison. Put fuller motivation, boundaries, and v1-to-v2 rationale in
  `docs/why-labtasker.md` rather than making every page equally long.
- Keep `docs/llms.txt` as a concise, curated map to the raw Markdown sources.
  Update it when a new page becomes a primary entry point or an existing linked
  page moves; do not turn it into a duplicate sitemap or a full documentation
  dump.
- Let the default getting-started path demonstrate the out-of-box experience:
  install, submit, and run first; explain the local Server and configuration
  afterward.
- Follow `docs/reference/specification.md` for exact behavior. If observable
  behavior changes, also use the `public-contract-change` skill and update the
  complete public slice.
- Do not promise capabilities that Labtasker does not own. Prefer concrete,
  verifiable statements over superlatives.
- Preserve unrelated worktree changes and never hand-edit generated `site/`.

For ambiguous positioning or structure work, discuss two to five high-leverage
questions per round with the user. Once the direction is clear, update all
affected documentation surfaces and run `uv run zensical build --clean` plus
relevant link checks. Perform the truth, relevance, and reader-interest fact
check above before handoff. Documentation-only changes do not require unrelated
runtime tests.
