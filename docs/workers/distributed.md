# Distributed launchers

Inference and evaluation Workers are Labtasker's primary use case. When one Task
instead needs a single-node distributed launcher for a larger evaluation or
training job, v2 supports `torchrun` and Accelerate. Start the launcher as the
child command of one Labtasker command Worker:

```bash
labtasker loop --route robotwin -- \
  torchrun --nproc-per-node=8 evaluate.py --task '%{task}'

labtasker loop --route robotwin -- \
  accelerate launch --num_processes 8 evaluate.py --task '%{task}'
```

This creates one Labtasker run, one heartbeat thread, and one local journal. The
launcher starts and manages its ranks. Starting an independent Labtasker loop inside
every rank would create competing Workers and is rejected before claim when the
runtime detects a distributed child process.

This integration has the same platform support as a command Worker: Linux is
release-gated, macOS is best effort, and Windows is rejected before Server access
because Labtasker cannot guarantee process-tree cancellation there.

## Reporting completion

Only one rank should call `finish()`. Use the launcher's own main-rank API
instead of assuming that every framework uses the same environment variables.

PyTorch example:

```python
import torch.distributed as dist

import labtasker

# TODO: Compute final_score in your evaluation code.
if dist.get_rank() == 0:
    labtasker.finish({"score": final_score})
```

Accelerate example:

```python
from accelerate import Accelerator

import labtasker

accelerator = Accelerator()
# TODO: Compute final_score in your evaluation code.
if accelerator.is_main_process:
    labtasker.finish({"score": final_score})
```

Labtasker passes the execution variables to every rank so the main rank can
report the result. Its at-fork guard clears the active Python execution context
in child processes, so a forked child cannot report for the parent's run.

Multi-node resource allocation and rendezvous are outside Labtasker. An external
scheduler should start the single Worker/launcher process with the resources it
needs.
