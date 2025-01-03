# Labtasker

## Introduction

Labtasker is an easy-to-use task queue system designed for dispatching lab experiment tasks to user-defined workers.

It enables users to submit various experiment arguments to a server-based task queue. Worker nodes can then retrieve and execute these tasks from the queue.

Unlike traditional HPC resource management systems like SLURM, ==**Labtasker is tailored for users rather than system administrators.**==

## Motivation

### Why not simple bash scripts?

Imagine you have several lab experiments to run on a single GPU, each with multiple parameters to configure.

The simplest approach is to create a script for each experiment and execute them sequentially.

```bash
for my_param_1 in 1 2 3 4; do
    for my_param_2 in 1 2 3 4; do
        for my_param_3 in 1 2 3 4; do
            python run_my_experiment.py --param1 $my_param_1 --param2 $my_param_2 --param3 $my_param_3
        done
    done
done
```

This method works, but what if you have more than one GPU?

Let's say you have 4 GPUs. You can split the experiments into 4 groups and run them in parallel to make better use of the GPU resources.

```bash
# Use my_param_1 to divide the experiments into 4 groups for 4 GPUs

# my_experiment_1.sh
my_param_1=1
for my_param_2 in 1 2 3 4; do
    for my_param_3 in 1 2 3 4; do
        python run_my_experiment.py --param1 $my_param_1 --param2 $my_param_2 --param3 $my_param_3
    done
done

# my_experiment_2.sh
my_param_1=2
for my_param_2 in 1 2 3 4; do
    for my_param_3 in 1 2 3 4; do
        python run_my_experiment.py --param1 $my_param_1 --param2 $my_param_2 --param3 $my_param_3
    done
done

# my_experiment_3.sh
my_param_1=3
for my_param_2 in 1 2 3 4; do
    for my_param_3 in 1 2 3 4; do
        python run_my_experiment.py --param1 $my_param_1 --param2 $my_param_2 --param3 $my_param_3
    done
done

# my_experiment_4.sh
my_param_1=4
for my_param_2 in 1 2 3 4; do
    for my_param_3 in 1 2 3 4; do
        python run_my_experiment.py --param1 $my_param_1 --param2 $my_param_2 --param3 $my_param_3
    done
done
```

However, this method can quickly become unwieldy and offers limited control over the experiments once the wrapper scripts are running.

- What if the parameters are difficult to divide, making it challenging to split the loop into multiple scripts?
- What if you realize some experiments are unnecessary while monitoring them live? You'd have to stop the script and modify it.
- What if you want to prioritize certain experiments after reviewing initial results? You'd have to stop the script and modify it.
- What if you want to add more experiments to the queue? You'd have to stop the script and modify it.
- What if some experiments fail? You'd need to create new scripts to restart them.

Labtasker is designed to overcome these challenges.

### Why not SLURM?

Labtasker is designed to be a simple and easy-to-use.

It disentangles task queue from resource management.
It offers a versatile task queue system that can be used by anyone (not just system administrators), without the need for extensive configuration or knowledge of HPC systems.

Here's are key conceptual differences between Labtasker and SLURM:

| Aspects          | SLURM                                                                 | Labtasker                                                                                      |
|------------------|------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| Purpose          | HPC resource management system                                         | Task queue system for lab experiments                                                          |
| Who is it for    | Designed for system administrators                                     | Designed for users                                                                             |
| Configuration    | Requires extensive configuration                                       | Minimal configuration needed                                                                   |
| Task Submission  | Jobs submitted as scripts with resource requirements                   | Tasks submitted as argument groups (JSON dictionaries)                                         |
| Resource Handling| Allocates resources and runs the job                                   | Does not explicitly handle resource allocation                                                 |
| Flexibility      | Assumes specific resource and task types                               | No assumptions about task nature, experiment type, or computation resources                    |
| Execution        | Runs jobs on allocated resources                                       | User-defined worker scripts run on various machines/GPUs/CPUs and decide how to handle the arguments        |
| Reporting        | Handled by the framework                                               | Reports results back to the server via API                                                     |
