import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={"CASE_ID": Path(__file__).parents[1].name},
)
