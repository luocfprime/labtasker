# Query language

Task list, count, and bulk update share one small expression language. Querying
never participates in Worker routing.

```text
priority >= 10 and metadata.group == "ablation"
"baseline" in metadata.tags
status == "failed" and last_error.type == "ValueError"
missing(result.accuracy) or result.accuracy < 0.9
```

## Values and paths

Literals use JSON spelling: strings, integers, floats, `true`, `false`, and
`null`. A path starts at the Task representation and traverses JSON objects with
dots, such as `metadata.group` or `result.metrics.accuracy`.

Supported top-level fields include `id`, `name`, `status`, `args`, `metadata`,
`priority`, `attempt`, `max_attempts`, `routes`, `result`, `last_error`,
`last_route`, and Task timestamps.

## Operators

```text
==  !=  <  <=  >  >=
in  not in
and or not
```

Parentheses control grouping. `in` is explicit about direction:

```text
"sdxl-v2" in routes
"owner" in metadata
```

For an object, membership checks keys. Reverse or ambiguous membership forms are
rejected instead of being assigned surprising semantics.

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
