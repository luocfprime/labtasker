# Embodied AI: RoboTwin evaluation (StarVLA codebase)

One StarVLA checkpoint must be evaluated across 50 RoboTwin manipulation tasks.
At first, running them on several GPUs appears to require only a loop. In
practice, balancing the work, tracking failures, and cleaning up every process
requires a 548-line Bash launcher.

## The application

[StarVLA](https://github.com/starVLA/starVLA/tree/0ed0aad2c83f587714f6167ef60cf7218b786590)
develops Vision-Language-Action policies that turn camera observations, robot
state, and language instructions into actions. Its
[RoboTwin 2.0 integration](https://github.com/starVLA/starVLA/blob/0ed0aad2c83f587714f6167ef60cf7218b786590/examples/simBenchmarks/Robotwin/README.md)
evaluates a policy on 50 simulated tasks in clean or randomized settings.

Each case starts a StarVLA policy server on a GPU and a RoboTwin simulator in a
separate Python environment. Cases are independent and may finish at different
times, so a free GPU should take the next case immediately.

## What the project has to maintain

StarVLA's
[`start_eval.sh`](https://github.com/starVLA/starVLA/blob/0ed0aad2c83f587714f6167ef60cf7218b786590/examples/simBenchmarks/Robotwin/eval_files/start_eval.sh)
already performs that dynamic scheduling. The launcher alone is 548 lines,
excluding the policy-server and evaluation scripts it invokes. It must discover
GPUs, allocate ports, track jobs and PIDs, wait for servers, refill free slots,
collect failures, organize logs, and recursively clean up processes.

Its scheduling shape, heavily abridged, looks like this:

```bash title="Abridged structure of the project scheduler"
--8<-- "snippets/case-studies/starvla-robotwin/custom_scheduler.sh"
```

This is reasonable engineering. Dynamic parallelism requires the launcher to
schedule jobs and manage processes. Progress is stored only in the launcher and
its logs, so after an interruption the researcher must determine what finished
before starting the next run.

## What Labtasker handles

The useful Task boundary is one checkpoint × RoboTwin task × mode. Submitting all
50 tasks in both modes creates 100 explicit Tasks:

=== "Submit Tasks"

    ```python title="submit.py"
    --8<-- "snippets/case-studies/starvla-robotwin/submit.py"
    ```

=== "Run one Worker per GPU"

    ```python title="worker.py"
    --8<-- "snippets/case-studies/starvla-robotwin/worker.py"
    ```

These excerpts show the design and are not a complete StarVLA integration. The
Worker contains the StarVLA-specific code for one case. Labtasker distributes
the cases and records progress, retries, recovery, and final status.

StarVLA and RoboTwin still own the policy, simulator, task definitions, metrics,
environments, logs, and videos. The researcher still chooses which GPUs run
Workers. Labtasker replaces only the project-specific coordination layer and
exposes the same operations to humans and agents.
