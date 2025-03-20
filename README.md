# Labtasker

![unit-test-matrix](https://github.com/fkcptlst/labtasker/actions/workflows/unit-test-matrix.yml/badge.svg)
[![codecov](https://codecov.io/gh/fkcptlst/labtasker/graph/badge.svg?token=KQFBV3QRPY)](https://codecov.io/gh/fkcptlst/labtasker)
![Python version](https://img.shields.io/badge/Python-3.8%20|%203.9%20|%203.10%20|%203.11%20|%203.12%20|%203.13-blue)
[![PyPI](https://img.shields.io/pypi/v/labtasker)](https://pypi.org/project/labtasker/)

**Labtasker makes lab experiment wrapper scripts smarter with task prioritization, failure handling, halfway resume and
more: just change 1 line of code.**

## When and Where to Use

**TLDR**: Replace `for` loops in your experiment *wrapper script* with labtasker to enable features like experiment
parallelization, dynamic task prioritization, failure handling, halfway resume, and more.

```diff
for script in eval/eval_model_A.py eval/eval_model_B.py
do
    for dataset in visualmrc_test halu_eval foo_eval bar_eval baz_eval
    do
-       # run sequentially with only 1 GPU :(
-       CUDA_VISIBLE_DEVICES=0 python $script --dataset $dataset
+       # submit the task args once
+       labtasker submit -- --exp_script $script --exp_dataset $dataset
    done
done
```

```diff
+ # parallelism across any number of workers effortlessly :)
+ CUDA_VISIBLE_DEVICES=0 labtasker loop -- python '%(exp_script)' --dataset '%(exp_dataset)' &
+ CUDA_VISIBLE_DEVICES=1 labtasker loop -- python '%(exp_script)' --dataset '%(exp_dataset)' &
...
+ CUDA_VISIBLE_DEVICES=7 labtasker loop -- python '%(exp_script)' --dataset '%(exp_dataset)' &
```

For detailed examples and concepts, check out the [documentation](https://fkcptlst.github.io/labtasker/).

## A Quick Demo

This demo shows how to easily submit task arguments and run jobs in parallel.

It also features an event listener to monitor task execution in real-time and automate workflows,
such as sending emails on task failure.

![demo](https://fkcptlst.github.io/labtasker/dev/assets/gifs/demo.cast)

## Features

- Easy configuration and setup.
- Versatile and intuitive.
- Supports both CLI and Python API for task scheduling.
- Customizable plugin system.

## Installation

To install client tools:

```bash
pip install labtasker
```

or

```bash
pip install git+https://github.com/fkcptlst/labtasker.git
```

## Quick Start

Use the following command to quickly setup a labtasker queue for your project:

```bash
labtasker init
```

Then, use `labtasker submit` to submit tasks and use `labtasker loop` to run tasks across any number of workers.

## Documentation

For detailed information on demo, tutorial, deployment, usage, please refer to
the [documentation](https://fkcptlst.github.io/labtasker/).
