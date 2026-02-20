# OpenCode Agent Skill

This page provides a skill definition for OpenCode agents to use Labtasker.

## Copy the Skill

Copy the following code block to your project at `.opencode/skills/labtasker/SKILL.md`:

````markdown
---
name: labtasker
description: Use Labtasker to distribute ML experiment tasks with queuing, prioritization, failure handling and resume
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: ml-experiments
---

## Overview

Labtasker is a CLI tool that turns your serial ML experiment scripts into distributed, manageable tasks. It replaces `for` loops in wrapper scripts with a task queue system.

**When to use**: You have a script like `for param in params: python train.py --param $param` and want to:
- Run experiments in parallel across multiple GPUs
- Handle failures gracefully (retry, resume from checkpoint)
- Prioritize or filter which tasks to run
- Track all experiment results in one place

**Links**: [GitHub](https://github.com/luocfprime/labtasker) | [Full Documentation](https://luocfprime.github.io/labtasker/)

## Core Concepts

### Queue
A queue is a named task bucket. All tasks belong to a queue. Workers pull tasks from a queue.
```bash
labtasker queue create-from-config  # Create queue from config
labtasker queue get                 # Get current queue info
```

### Task
A task has:
- `args`: Key-value pairs that get interpolated into the run command
- `metadata`: Custom tags/info for filtering (e.g., `{"tags": ["experiment-v1"]}`)
- `name`: Optional task name
- `status`: pending → running → success/failed

### Loop
The `labtasker loop` command runs continuously, fetching pending tasks and executing them.

## Complete Workflow (with Demo)

### Step 1: Setup

```bash
# Install
pip install labtasker

# Start server (in background)
labtasker-server serve &

# Initialize - creates config interactively
labtasker init

# Create queue
labtasker queue create-from-config
```

### Step 2: Submit Tasks

Convert your parameter grid into task submissions:

```bash
#!/bin/bash
# submit_job.sh - submit all task variations

for arg1 in {0..2}; do
    for arg2 in {3..5}; do
        labtasker task submit --name grid_search --metadata '{"tags": ["experimental"]}' -- --arg1=$arg1 --arg2=$arg2
    done
done
```

### Step 3: Run Tasks

```bash
#!/bin/bash
# run_job.sh - execute tasks

labtasker loop -- python train.py --arg1 '%(arg1)' --arg2 '%(arg2)'
```

The `%(arg1)` syntax pulls values from task args and substitutes them at runtime.

### Check Status

```bash
labtasker task ls -s pending    # View pending tasks
labtasker task ls -s running    # View running tasks
labtasker task ls -s success   # View completed tasks
labtasker task ls -s failed    # View failed tasks
```

## Filtering Tasks

Filtering is powerful for selecting specific tasks:

### Python Native Syntax (recommended)

```bash
# Filter by argument value
labtasker task ls -f 'args.foo.bar > 0.1' --quiet --no-pager

# Filter by task name
labtasker task ls -f 'task_name == "grid_search"' --quiet --no-pager

# Filter by metadata tags
labtasker task ls -f 'metadata.tags in ["experimental", "test"]' --quiet --no-pager

# Filter by date (relative or absolute)
labtasker task ls -f 'created_at >= date("3 hours ago")' --quiet --no-pager

# Combine conditions with AND/OR
labtasker task ls -f 'args.foo.bar > 0.1 and metadata.tags in ["experimental"]' --quiet --no-pager

# Use regex
labtasker task ls -f 'regex(task_name, "^exp-.*")' --quiet --no-pager
```

**Supported operators**: `==`, `>`, `<`, `>=`, `<=`, `in`, `and`, `or`, `regex()`, `date()`
**Note**: `!=`, `not`, `not in` are NOT supported (null value ambiguity in three-valued logic)

### Using Filter in Loop

```bash
# Only execute tasks with specific tags
labtasker loop --extra-filter 'metadata.tags in ["experimental"]' -- python job.py '%(prompt)'
```

## Task Management

```bash
# Update task arguments
labtasker task update --id <task_id> -u 'args.arg1=0.3'

# Delete old tasks (pipe ls output to delete)
labtasker task ls -f 'created_at > date("10 minutes ago")' -q | labtasker task delete -y
```

## Key Principles (Critical!)

### 1. No More, No Less Rule
Labtasker fetches tasks based on exact field matching:
- **No More**: Don't submit extra fields that your run script doesn't use
- **No Less**: Your run script MUST use ALL submitted fields

```bash
# WRONG - submit has guidance_scale but run doesn't use it
labtasker task submit -- --prompt="hello" --guidance_scale=7.5
labtasker loop -- python job.py --prompt '%(prompt)'
# Result: task fetched but guidance_scale=7.5 ignored, inconsistency in logs

# WRONG - run uses extra_field but submit didn't provide it
labtasker task submit -- --prompt="hello"
labtasker loop -- python job.py --prompt '%(prompt)' --extra_field '%(extra_field)'
# Result: fetch fails because extra_field is required but not in args

# CORRECT - exact match
labtasker task submit -- --prompt="hello" --guidance_scale=7.5
labtasker loop -- python job.py --prompt '%(prompt)' --guidance_scale '%(guidance_scale)'
```

### 2. Argument Normalization
Labtasker normalizes arguments automatically. DON'T do it yourself:

```bash
# WRONG - normalizing yourself breaks the contract
# Submit: --value_a=1
# Run:   --value_a 1    (wrong!)

# CORRECT - let Labtasker handle it
# Submit: --value_a=1
# Run:   --value_a '%(value_a)'   (Labtasker normalizes automatically)
```

### 3. Environment Variables Placement
```bash
# WRONG - env var goes inside loop
labtasker loop -- CUDA_VISIBLE_DEVICES=0 python main.py

# CORRECT - env var goes outside loop
CUDA_VISIBLE_DEVICES=0 labtasker loop -- python main.py
```

### 4. Special Characters in Arguments
```bash
# For negative numbers, empty strings, or strings with spaces:
labtasker task submit -- --value=-1 --value="" --value="hello world"
```

### 5. Using %(variable) in Complex Scripts
If your run script has complex logic needing `%(variable)` interpolation, use `--script-path`:

```bash
# Write script to temp file with interpolation placeholders
LABTASKER_TASK_SCRIPT=$(mktemp)
cat <<'EOF' > "$LABTASKER_TASK_SCRIPT"
python train.py --dataset %(dataset) --model %(model)
EOF

labtasker loop --script-path $LABTASKER_TASK_SCRIPT
```

## Error Handling

When a task fails during `labtasker loop`:
1. **Report** (default): Mark task as failed, decrement retry count, task goes back to pending or stays failed
2. **Ignore**: Reset task to pending as if nothing happened, continue to next task (useful for debugging)

## Common Patterns

### Pattern 1: Simple Parameter Grid
```bash
# Submit
for lr in 0.001 0.01 0.1; do
    labtasker task submit -- --lr=$lr
done

# Run
labtasker loop -- python train.py --lr '%(lr)'
```

### Pattern 2: Multiple Parameters with Tags
```bash
# Submit
for model in resnet vit transformer; do
    for dataset in cifar10 imagenet; do
        labtasker task submit --metadata "{\"tags\": [\"$model\", \"$dataset\"]}" -- --model=$model --dataset=$dataset
    done
done

# Run
labtasker loop -- python train.py --model '%(model)' --dataset '%(dataset)'
```

### Pattern 3: Resume Failed Experiments
```bash
# After fixing the issue, re-run only failed tasks
labtasker loop --extra-filter 'status == "failed"' -- python train.py '%(args)'
```

## Quick Reference

| Command | Description |
|---------|-------------|
| `labtasker init` | Initialize config interactively |
| `labtasker queue create-from-config` | Create queue |
| `labtasker task submit -- --key=value` | Submit task |
| `labtasker loop -- cmd '%(arg)'` | Run tasks |
| `labtasker task ls -f 'filter'` | Query tasks |
| `labtasker task ls -s pending` | List by status |
| `labtasker task update -u 'args.k=v'` | Update task |
| `labtasker task delete` | Delete tasks |

## Skill Usage

1. Load skill: `skill({ name: "labtasker" })`
2. Identify the serial loop in user's experiment script
3. Split into submit script (generates all parameter combinations) and run script (template with %(variables))
4. Apply "No More, No Less" rule - ensure submit and run scripts have matching fields
5. Use metadata/tags for organizing experiments
6. Reference full documentation for advanced features
````
