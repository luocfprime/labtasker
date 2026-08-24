---
name: skill-development
description: Develop or revise Labtasker's public Agent Skill with adversarial QA between a full-repository Question Agent and a skills-only Answer Agent. Use when changing skills/labtasker, checking whether it covers realistic usage and capability questions, or splitting it into focused references; do not use for ordinary product documentation alone.
---

# Develop the public Agent Skill

Treat `skills/labtasker/` as an executable knowledge boundary. Test whether an
agent that knows nothing else about the repository can use it to answer realistic
Labtasker questions correctly and safely.

## Keep the two roles isolated

Use separate agents with asymmetric access:

- The **Question Agent** may read the complete current repository. It writes the
  questions, keeps the answer key private, grades the answers, and revises
  `skills/labtasker/` after each round.
- The **Answer Agent** may read only `skills/`. It answers only from those files
  and must not inspect source code, tests, ordinary documentation, git history,
  generated files, or the Question Agent's answer key.
- The orchestrating agent enforces the boundary, reviews every edit, and keeps
  unrelated worktree changes intact.

Use a fresh Answer Agent for each round. Do not send it earlier grading notes or
gold answers. Ask it to list the skill files it used so accidental access is
visible.

## Ask useful, difficult questions

The Question Agent should try to expose real gaps, not win with trivia. Build a
mixed holdout set covering:

- installation, first use, and the default local workflow;
- routine submission, Worker design, inspection, filtering, and recovery through
  both Python and shell/CLI interfaces;
- configuration, shared deployment, authentication, and platform boundaries;
- whether Labtasker supports a requested capability;
- choosing among plausible paths, including automatic local mode, a self-managed
  HTTP Server, Unix-socket requests, Windows, and multi-machine use;
- whether and how Labtasker fits a concrete ML inference, evaluation, or
  experiment workflow; and
- common misuses involving GPUs, clusters, DAGs, artifacts, concurrency, routes,
  retries, cancellation, or completed Tasks.

Prefer scenario questions such as “Can I do this, and what would the setup look
like?” Include enough context for one defensible answer. Do not ask about SQL,
private functions, internal class names, test fixtures, migration mechanics, or
other details a user should not need.

Balance each round across the synchronous Python Client API, Python Worker API,
CLI, and Command Worker. Do not let CLI examples stand in for Python coverage or
vice versa. Re-test important behavior through a different public interface in a
later round when the contract is meant to be consistent.

Derive the private answer key from `docs/reference/specification.md`, the current
public interfaces, and executable behavior. Record any disagreement between the
specification and implementation instead of teaching either one silently.

## Run the QA loop

For every round:

1. Have the Question Agent prepare 10–16 new or materially varied questions and
   a private rubric. Give only the questions to the Answer Agent.
2. Have the Answer Agent answer concretely, distinguish supported behavior from
   external responsibilities, choose the documented canonical path, and cite the
   relevant file under `skills/`.
3. Have the Question Agent grade each answer as optimal, acceptable but
   non-canonical, partial, or incorrect. A technically possible answer is not
   optimal when it bypasses the supported public interface, adds unnecessary
   setup, or ignores a simpler documented default. Treat invented capabilities,
   unsafe lifecycle advice, and wrong platform or deployment claims as critical
   errors.
4. Have the Question Agent revise `skills/labtasker/` for general coverage, not
   merely paste answers to the test. Prefer clearer decision rules, a small
   example, or a focused reference over a growing list of exceptions.
5. Review the diff and fact-check the revision against the specification and
   current public behavior. Then start a fresh Answer Agent with a new holdout
   set.

Run at least three rounds. Later rounds should target ambiguity and transfer to
new scenarios, not repeat the same wording.

## Keep the public skill compact

Keep `skills/labtasker/SKILL.md` as a short entry point containing the product
boundary, the default workflow, and explicit directions for which reference to
read. Put conditional or lower-frequency material in a few purpose-named files
under `skills/labtasker/references/`.

Each fact should have one natural home. References must be linked directly from
the entry skill; do not create a deep tree or a second documentation site. Avoid
including implementation details solely because the Question Agent can see
them.

## Stop only after a holdout converges

Consider the skill converged when all of the following hold:

- at least three QA rounds used fresh Answer Agents and materially different
  questions;
- the final round has no critical error and at least 90% of answers are fully
  correct;
- ordinary usage and “does it support this?” questions are answered without
  repository access;
- the Answer Agent consistently selects the recommended path and clearly labels
  merely possible, unsupported, or externally owned alternatives;
- remaining misses are genuinely out of scope for a public skill rather than
  missing user-facing guidance; and
- the entry skill remains short enough to read in full before following only the
  references relevant to the request.

Validate the skill structure and links after the final edit. If the public skill
or its installation instructions changed, also update the maintained Agent Skill
guide and run the documentation build.
