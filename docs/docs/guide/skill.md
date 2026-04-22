# Claude Code Skill

Labtasker provides a skill definition for Claude Code. With it installed, Claude understands how to write submit scripts, run scripts, and task management scripts — in both CLI and Python — including metadata, filtering, updating, deleting, and reading task summaries.

## Install

**Via marketplace (recommended)**

```bash
/plugin marketplace add luocfprime/labtasker
/plugin install labtasker-skill@labtasker
```

**Manual**

Create `~/.claude/skills/labtasker/SKILL.md` with the following content:

````markdown
--8<-- "skills/labtasker/SKILL.md"
````
