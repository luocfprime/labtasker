# Agent skill

Labtasker ships one `labtasker` skill that teaches coding agents the v2 Task,
Queue, route, Worker, query, and recovery workflows. The canonical source is
[`skills/labtasker/SKILL.md`](https://github.com/luocfprime/labtasker/blob/v2/skills/labtasker/SKILL.md).

## LLM-readable documentation

The Agent Skill teaches an agent how to operate Labtasker. The documentation
site's `llms.txt` helps an agent find the right supporting documentation. It is
published at the documentation root and links directly to the raw Markdown for
the main guides, API references, and authoritative specification. The
[`llms.txt` source](https://raw.githubusercontent.com/luocfprime/labtasker/refs/heads/v2/docs/llms.txt)
can also be read directly.

## Claude Code marketplace

Add the repository as a marketplace, then install its plugin:

```text
/plugin marketplace add luocfprime/labtasker@v2
/plugin install labtasker-skill@labtasker
```

The installed skill is invoked as `/labtasker-skill:labtasker`. Claude Code can
also select it automatically when a request matches its description.

## Agent Skills CLI

The open Agent Skills installer supports Claude Code, Codex, OpenCode, Cursor,
and other compatible agents:

```bash
npx skills add \
  https://github.com/luocfprime/labtasker/tree/v2/skills/labtasker
```

The direct v2 skill path keeps contributor-only repository workflows out of the
installation. The installer prompts for target agents and project or global
scope. For a non-interactive Codex installation, for example:

```bash
npx skills add \
  https://github.com/luocfprime/labtasker/tree/v2/skills/labtasker \
  --agent codex --global --yes
```

Use `--agent claude-code` instead to install through the same open skill format
without using the Claude Code marketplace.

## Repository checkouts

This repository exposes the same canonical content at
`.agents/skills/labtasker` for repository-aware agents. It is a relative symlink,
so the three discovery mechanisms cannot drift into independent copies.

The agent skill describes the public Labtasker product. Contributor-only
workflows such as releases and cross-surface contract changes remain separate
under `.agents/skills/` and are documented in [Development](../development.md).
