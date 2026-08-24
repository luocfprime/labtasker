# Architectural excerpt: run one Worker on each selected GPU.
import labtasker


@labtasker.loop(route="robotwin")
def evaluate(
    checkpoint: str = labtasker.TaskArg(),
    task: str = labtasker.TaskArg(),
    mode: str = labtasker.TaskArg(),
    seed: int = labtasker.TaskArg(),
) -> None:
    result = run_one_robotwin_case(checkpoint, task, mode, seed)
    labtasker.finish(
        {
            "success_rate": result.success_rate,
            "log": str(result.log_path),
        }
    )


evaluate()
