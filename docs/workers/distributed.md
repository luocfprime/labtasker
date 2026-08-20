# Distributed launchers

Labtasker v2 supports the single-node launcher pattern used by `torchrun` and
Accelerate. Keep the Labtasker Worker outside the launcher:

```bash
labtasker loop --route train -- \
  torchrun --nproc-per-node=8 train.py --lr '%{lr}'

labtasker loop --route train -- \
  accelerate launch --num_processes 8 train.py --lr '%{lr}'
```

This creates one Labtasker run, one heartbeat thread, and one local journal. The
launcher owns its child ranks. Starting an independent Labtasker loop inside
every rank would create competing Workers and is rejected before claim when the
runtime detects a distributed child process.

## Reporting completion

Only one rank should call `finish()`. Prefer the launcher's own main-rank API,
which is more reliable than assuming every framework uses the same environment
variables.

PyTorch example:

```python
import torch.distributed as dist

import labtasker

if dist.get_rank() == 0:
    labtasker.finish({"loss": final_loss})
```

Accelerate example:

```python
from accelerate import Accelerator

import labtasker

accelerator = Accelerator()
if accelerator.is_main_process:
    labtasker.finish({"loss": final_loss})
```

The execution environment is deliberately inherited by all ranks so the main
rank can report. Labtasker's at-fork guard clears an in-memory Python execution
context in child processes, preventing a forked child from inheriting ownership
of the parent's active run.

Multi-node resource allocation and rendezvous are outside Labtasker. An external
scheduler should start the single Worker/launcher process with the resources it
needs.
