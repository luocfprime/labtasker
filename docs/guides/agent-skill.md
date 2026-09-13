# Agent Skill

Without a shared workflow, a coding agent must rediscover how each project
distributes jobs, records progress, retries failures, and collects results.
Labtasker's `labtasker` skill supplies those operating rules, so a request such
as “run these cases in parallel across 8 GPUs with Labtasker” is enough to start
the standard Labtasker workflow.

The skill covers v2 Task submission, Worker design, routing, inspection,
updates, recovery, and adapting an existing experiment pipeline. It also explains
how to compare pending Task demand with observed Worker activity through
Python or CLI grouped counts, including pagination and delayed observations.
It teaches Workers to publish replace-only progress snapshots, the optional
`completed`/`total` display convention, and how an external controller can apply
a user-defined early-stop rule before requesting cooperative cancellation.
It covers fuzzy Task name search, advisory Server version warnings, and the
Worker’s consecutive-failure limit without confusing it with Task retry budgets.
During a migration it asks about the project's entry points, reusable setup,
retry units, resources, dependencies, and outputs, then owns the mapping into Labtasker
instead of requiring a newcomer to design Tasks, Workers, routes, or Queues. It
does not choose the experiment, allocate GPUs, or keep the agent inside the
execution loop. Its short
[`SKILL.md`](https://github.com/luocfprime/labtasker/blob/main/skills/labtasker/SKILL.md)
routes deployment, Worker, inspection, and recovery questions to focused references;
the official installable package is
[`skills/labtasker/`](https://github.com/luocfprime/labtasker/tree/main/skills/labtasker).

## LLM-readable documentation

The Agent Skill teaches an agent how to operate Labtasker. A built documentation
site exposes [`llms.txt`](https://luocfprime.github.io/labtasker/latest/llms.txt)
to help an agent find the right supporting material. It links directly to the
raw Markdown for the main guides, API references, and full specification. The
[`llms.txt` source](https://raw.githubusercontent.com/luocfprime/labtasker/refs/heads/main/docs/llms.txt)
can also be read directly.

## Claude Code marketplace

Add the repository as a marketplace, then install its plugin:

```text
/plugin marketplace add luocfprime/labtasker
/plugin install labtasker-skill@labtasker
```

The installed skill is invoked as `/labtasker-skill:labtasker`. Claude Code can
also select it automatically when a request matches its description.

## Agent Skills CLI

The open Agent Skills installer supports Claude Code, Codex, OpenCode, Cursor,
and other compatible agents:

```bash
npx skills add \
  https://github.com/luocfprime/labtasker/tree/main/skills/labtasker
```

The direct skill path keeps contributor-only repository workflows out of the
installation. The installer prompts for target agents and project or global
scope. For a non-interactive Codex installation, for example:

```bash
npx skills add \
  https://github.com/luocfprime/labtasker/tree/main/skills/labtasker \
  --agent codex --global --yes
```

Use `--agent claude-code` instead to install through the same open skill format
without using the Claude Code marketplace.

## Repository checkouts

This repository exposes the same skill content at
`.agents/skills/labtasker` for repository-aware agents. It is a relative symlink,
so every discovery method reads the same files.

The agent skill describes the public Labtasker product. Contributor-only
workflows such as releases and cross-surface contract changes remain separate
under `.agents/skills/` and are documented in [Development](../development.md).

## Maintaining the skill

The public skill and its bundled references are maintained together. Feature
changes should update the relevant reference and add a realistic agent scenario
to the [skill regression suite](https://github.com/luocfprime/labtasker/tree/main/tests/skill).
The suite separates candidate requests from examiner setup and checks. Candidates
operate only in temporary test environments, using the skill and public
interfaces. Test fixtures and grading rules are not part of the installed skill.
Questions describe ordinary user goals without prescribing the API, commands,
steps, or expected answer. The examiner checks whether the goal was met, whether
the agent interpreted the results correctly, and whether it made unnecessary
changes or requests for clarification. Low-level product invariants remain in
the ordinary automated tests.

See [Development](../development.md#agent-workflows) for the examination and
revision workflow. Executable setup/check validation and an independent agent
pass are separate results; neither guarantees support on untested platforms.
