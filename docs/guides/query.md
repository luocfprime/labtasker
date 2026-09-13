# Query Tasks

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
nullable `progress`, `last_route`, and Task timestamps. Dynamic paths such as
`progress.metrics.val_loss` select Tasks whose latest reported snapshot contains
that path.

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

## Find a remembered name

Use fuzzy name search when you remember parts of an experiment label:

```bash
labtasker task list --name-fuzzy 'tr ev' --status pending
labtasker task count --name-fuzzy 'tr ev' --status pending
```

In Python, use `list_tasks(name_fuzzy="tr ev", status="pending")` or
`count_tasks` with the same selectors. Each word must appear as a subsequence
of the name, ignoring case: both `tr ev` and `EV TR` match `train_model_eval`.
Words may overlap and match in any order. Punctuation is literal; there are no
wildcards, regex operators, or relevance ranking. An empty or whitespace-only
query adds no restriction.

Exact `name`, `name_fuzzy`, `status`, and `filter` combine with AND. Fuzzy
matching is available on list and count, not inside filter expressions or as a
bulk-update selector. Inspect matches before changing Tasks by ID or a supported
filter.

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
Keep the raw fuzzy query unchanged too, including its case and whitespace.
CLI list returns only one page. Continue with `--cursor` until `next_cursor` is
null; Python callers pass it as `cursor=`. Pages read live state rather than one
snapshot.

## Compare waiting work with observed Workers

Group pending Tasks by compatible route, then inspect Worker activity:

```bash
labtasker task count --status pending --group-by routes
labtasker worker count --group-by route,status
labtasker worker list --filter 'route == "sdxl" and status == "idle"'
```

Task grouping supports `routes` and `status`; Worker grouping supports `route`
and `status`. Python accepts a list such as `group_by=["route", "status"]`,
while CLI accepts one comma-separated value. Filters select records before
grouping. Worker filters use observation fields, not Task args or metadata.

Grouped responses contain `group_by`, `count`, `items`, and `next_cursor`.
The top-level `count` is the complete selected total. A Task accepting two routes
appears in both route groups, so summing those groups double-counts it. `limit`
limits groups, not Tasks. Follow every group page with the same selection and
ordered grouping fields; do not add the totals from successive pages. Without
grouping, counting returns a scalar in Python and `{"count": N}` in CLI.

Align the two sets of route groups locally. Worker observations are approximate
presence: they expire, do not reserve capacity, and cannot establish Task
ownership. A busy Worker may still be cleaning up after an already succeeded
Task. Missing observations must not cause cancellation or requeue. A failed
query is unavailable information, not a zero count.

See [Manage Tasks](tasks.md#diagnose-pending-routes) for monitoring
examples and [Python API](../reference/python-api.md#grouped-counts) for exact
models and cursor rules.
