# Worker observations and grouped counts

## Inspect presence without inferring ownership

Bundled Python and Command Workers automatically report one observation per
Worker loop invocation, including idle periods. No registration setup or stable
Worker name is needed. A fresh invocation gets a fresh `w_` ID, even in the same
process; reconnects retain that ID. An outer Command Worker is observed once;
its command child and distributed ranks are not separate Workers. Restarted and
old observations can briefly overlap.

Observations renew every 60 seconds and expire 300 seconds after the last
accepted report, with best-effort activity-change reports. These timings are
independent of Task heartbeats and ownership leases. Only unexpired observations
appear in Worker queries. Use the Server-provided `expires_at` for freshness.
There is no offline history, Worker get, hostname/PID/name inventory, remote
start/stop/restart command, or resource allocator.

- `idle`: waiting for work, including an unconfirmed claim response.
- `busy`: a confirmed claim occupies the Worker through execution, terminal
  reporting, and cleanup. Accepted `finish()` may make the Task succeeded while
  its Worker stays busy until local execution and cleanup end.

Public fields are `id`, `queue`, `route`, `status`, nullable advisory `task_id`,
`last_seen_at`, and `expires_at`. Timestamps are Server-generated UTC. The Task
reference may be terminal, stale, or deleted; it is not an ownership token.
Route presence means any idle or busy observation for that exact route in that
Queue. It does not prove spare capacity, compatibility of undocumented settings,
or the absence of other execution processes when zero Workers are observed.

Report failures never block startup, claims, execution, Task reports, or the
failure guard. A lost observation must not trigger cancellation or requeue:
Tasks remain authoritative under their own lease and `run_id` fencing. Once the loop has independently decided to
exit, it attempts withdrawal, waiting at most one second. This does not limit execution/cleanup or initiate exit. Crashes and
failed withdrawals fall back to expiry. Worker observations do not prevent Queue
deletion; Task-based deletion rules still apply.

## Read Workers

```bash
labtasker worker list --queue experiments --filter 'status == "busy"' --limit 100
labtasker worker count --queue experiments --group-by route,status
```

```python
from labtasker import Client

with Client(queue="experiments") as client:
    page = client.list_workers(filter='status == "busy"', limit=100)
    total = client.count_workers()  # int
    groups = client.count_workers(group_by=["route", "status"])
```

Module-level `labtasker.list_workers()` and `labtasker.count_workers()` expose
the same interface. Listing returns `WorkerPage(items, next_cursor)` containing
`WorkerObservation` values. Follow every non-null cursor with the same Queue
and exact filter. Lists are ordered by ID lexicographically ascending, with no
`order_by` option. Page sizes default to 100, maximum 1000. Reads are live, not
a snapshot spanning pages.

Worker filters use the existing expression language over the seven public
Worker fields only. For example, `route == "judge" and status == "idle"` or
`task_id == None`. Use `filter=...`, not a separate Worker `status=` selector;
Task paths such as `args` or `metadata` are not Worker fields. An API/transport
error means the query failed, never an empty Worker inventory.

## Count selected Tasks and Workers

```bash
labtasker task count --status pending --group-by routes
labtasker task count --filter 'metadata.batch == "pilot"' --group-by status,routes
labtasker worker count --group-by route
```

```python
with Client() as client:
    demand = client.count_tasks(status="pending", group_by=["routes"])
    presence = client.count_workers(group_by=["route", "status"])
```

To diagnose waiting work, fully read pending Task groups by `routes` and
independently read Worker groups by `route`, then align those results locally.
There is no joined summary or Route registry. Worker-only routes may also be
shown. Worker presence and Task demand can change between these reads.

| Operation | Allowed grouping dimensions |
| --- | --- |
| `count_tasks` / `task count` | `routes`, `status`, or both in either order |
| `count_workers` / `worker count` | `route`, `status`, or both in either order |

Task `routes` means compatible route membership, including for running Tasks;
it does not mean the route that actually executed the Task. There is no grouping
by `last_route`, metadata, arbitrary expressions, or additional metrics. Filter
on supported Task fields before aggregation instead. Without grouping, Python
returns an integer and HTTP/CLI return `{"count": n}`. Do not pass `limit` or
`cursor` for an ungrouped count.

Python grouping takes an ordered list or tuple, never a comma-separated string.
CLI/HTTP grouping takes one comma-separated value without spaces, for example
`--group-by routes,status`. Empty values, duplicates, whitespace, unsupported
fields, and repeated CLI options are errors rather than normalized inputs.

Grouped Python calls return `GroupCountPage` with `CountGroup` items. HTTP/CLI
return the same structure as JSON. Example for two pending Tasks accepting
`["a", "b"]` and `["a"]`:

```json
{
  "group_by": ["routes"],
  "count": 2,
  "items": [
    {"key": {"routes": "a"}, "count": 2},
    {"key": {"routes": "b"}, "count": 1}
  ],
  "next_cursor": null
}
```

The top-level `count` is the complete deduplicated selected total, not a page
subtotal. Never sum overlapping Task route groups to obtain a Task total. Each
key is an object with string values; `group_by` defines dimension order. Groups
sort lexicographically by those dimensions, including status (not lifecycle
order). Only nonzero groups are returned; a missing group can mean zero only
after all relevant pages have been read.

## Follow group pages

Grouping is computed over the complete Server-side selection before pagination.
`limit` counts groups, defaults to 100, and must be 1–1000. CLI returns one page;
it does not automatically fetch the rest. For example:

```python
with Client() as client:
    selection = dict(
        status="pending",
        filter='metadata.batch == "pilot"',
        group_by=["status", "routes"],
    )
    cursor = None
    while True:
        page = client.count_tasks(**selection, limit=100, cursor=cursor)
        for group in page.items:
            print(group.key, group.count)
        cursor = page.next_cursor
        if cursor is None:
            break
```

Use the same operation, Queue, exact filter/Task selectors, and ordered grouping
fields for continuation. Page size may change. Do not reuse list cursors for
counts, Task cursors for Workers, or cursors with reordered dimensions or a
rewritten filter. Cursors are opaque. Invalid/mismatched cursors are errors.
Each page reads current data: its total and groups may change while paging, so
combining pages does not give an atomic snapshot. Do not add page totals.

Old Clients do not report observations. New Workers can execute against older
Servers even when observation calls fail. A grouped request receiving an old
scalar count response raises `TransportError`; do not display zero or silently
aggregate a partial Task list as a replacement. Report the unavailable query and
use matching Client/Server versions when these inspection features are needed.
