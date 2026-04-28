# Agent Skill

Labtasker provides a skill definition for AI coding agents. With it installed, agents understand how to write submit scripts, run scripts, and task management scripts — in both CLI and Python — including metadata, filtering, updating, deleting, and reading task summaries.

## Install

**Via Claude Code marketplace (recommended)**

```bash
/plugin marketplace add luocfprime/labtasker
/plugin install labtasker-skill@labtasker
```

**Other agents via `npx skills add`**

```bash
npx skills add luocfprime/labtasker
```

**Manual**

Create `~/.claude/skills/labtasker/SKILL.md` with the following content:

````markdown
--8<-- "skills/labtasker/SKILL.md"
````
