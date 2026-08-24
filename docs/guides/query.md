# Query language

Use filters to find unfinished work, inspect failures or outliers, and update a
selected group of Tasks. Task list, count, and bulk update share the same small
expression language, so a selection can be checked before it is changed.

Queries never decide which Worker may run a Task. Worker compatibility is set
only through routes.

```text
priority >= 10 and metadata.group == "ablation"
"baseline" in metadata.tags
status == "failed" and last_error.type == "ValueError"
missing(result.score) or result.score < 0.9
```

## Values and paths

Literals use Python spelling: strings, integers, floats, `True`, `False`, and
`None`. A path starts at the Task representation and traverses JSON objects with
dots, such as `metadata.benchmark` or `result.metrics.f1`.

Supported top-level fields include `id`, `name`, `status`, `args`, `metadata`,
`priority`, `attempt`, `max_attempts`, `routes`, `result`, `last_error`,
`last_route`, and Task timestamps.

## Operators

```text
==  !=  <  <=  >  >=
in  not in
and or
```

Parentheses control grouping. `in` is explicit about direction:

```text
status in ["failed", "cancelled"]
"sdxl-v2" in routes
```

`path in [value, ...]` checks a scalar against a candidate list.
`value in path` checks whether an array-valued path contains that value. It does
not test object keys: use `exists(metadata.owner)` for that. General unary
`not (...)` is unsupported; use `!=`, `not in`, `exists`, or `missing` instead.

## Missing values

Ordinary comparisons require a path to exist. Missing data does not silently
behave like `null` or `false`. State the intended behavior:

```text
exists(metadata.owner)
missing(metadata.owner)
missing(result.score) or result.score < 0.5
```

`exists(path)` and `missing(path)` are the only path-existence tests.

## Ordering and pagination

List queries choose one stable order field and direction:

```bash
labtasker task list \
  --filter 'status == "pending"' \
  --order-by priority \
  --descending \
  --limit 100
```

The Server adds Task ID as a deterministic tie-breaker. A cursor must be reused
with the same Queue, filter, selectors, order field, and direction.
