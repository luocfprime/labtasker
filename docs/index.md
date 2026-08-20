# Labtasker v2

Labtasker is a small task queue for parallel machine-learning experiments. It
coordinates Tasks and Workers while leaving resource allocation to the system
that starts those Workers.

Its central rule is explicit routing:

- every Task names one or more compatible routes;
- every Worker claims through exactly one route;
- a Task can be claimed only when those route labels match exactly.

There is one durable Server, a synchronous Python Client, and two Worker styles:
a Python function Worker and a command Worker. The Server does not keep a Worker
registry, infer capabilities from arguments, or allocate GPUs.

## Choose a starting point

- [Get started](getting-started.md) runs a Server, submits a Task, and executes it.
- [Core model](concepts.md) explains queues, routes, attempts, and run fencing.
- [Python Workers](workers/python.md) bind typed Task arguments to a function.
- [Command Workers](workers/command.md) bind Task arguments to an argv template.
- [Task operations](guides/tasks.md) covers submission, inspection, updates, and
  lifecycle actions.
- [HTTP API](reference/http-api.md) points agents and integrations to the live
  machine-readable contract.

## Design boundary

Labtasker aims to be complete inside a deliberately small boundary. It is not a
cluster scheduler, workflow DAG engine, artifact store, or agent-in-the-loop
runtime. An agent can configure and supervise an experiment, but execution and
recovery remain deterministic after the Worker starts.

The standalone
[v2 specification](https://github.com/luocfprime/labtasker/blob/v2/LABTASKER_V2_SPEC.md)
is authoritative when this guide omits protocol detail.
