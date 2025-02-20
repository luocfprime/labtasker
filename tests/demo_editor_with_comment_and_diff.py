import tempfile
from datetime import datetime
from typing import Any, Dict, List, Set

import click
import ruamel.yaml
import yaml

from labtasker.api_models import Task, TaskUpdateRequest
from labtasker.client.core.cli_utils import ls_yaml_format_iter


def commented_seq_from_dict_list(
    entries: List[Dict[str, Any]]
) -> ruamel.yaml.CommentedSeq:
    return ruamel.yaml.CommentedSeq([ruamel.yaml.CommentedMap(e) for e in entries])


def main():
    readonly_fields: Set[str] = (
        Task.model_fields.keys() - TaskUpdateRequest.model_fields.keys()  # type: ignore
    )
    readonly_fields.add("task_id")

    # simulated data entries
    entries = [
        Task(
            _id="8c6e3889-4c33-4e62-ad29-a98eed7c7ac4",  # noqa
            queue_id="1a709bc6-7d5e-442b-a16e-2729f9106baf",
            status="pending",
            priority=1,
            retries=0,
            max_retries=3,
            heartbeat_timeout=60.0,
            task_timeout=None,
            task_name=None,
            metadata={},
            summary={},
            args={"arg1": 2, "arg2": 5},
            cmd="",
            start_time=None,
            last_heartbeat=None,
            worker_id=None,
            created_at=datetime.now(),
            last_modified=datetime.now(),
        ).model_dump()
        for _ in range(10)
    ]

    data = commented_seq_from_dict_list(entries)

    # set line break at each entry
    for i in range(len(data) - 1):
        data.yaml_set_comment_before_after_key(key=i + 1, before="\n")

    for d in data:
        for key in d.keys():
            if key in readonly_fields:
                d.yaml_add_eol_comment("Read-only. DO NOT modify!", key=key, column=50)

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml") as f:
        print(f"Editing file {f.name}")
        y = ruamel.yaml.YAML()
        y.indent(mapping=2, sequence=2, offset=0)
        y.dump(data, f)
        click.edit(filename=f.name)

        f.seek(0)
        data = yaml.safe_load(f)

    updates = []
    for i, d in enumerate(data):
        update_dict = dict()
        for key, value in d.items():
            if key in readonly_fields:
                print(f"{key} is read-only. Skipping...")
                continue
            elif value == entries[i][key]:
                print(f"{key} is unchanged. Skipping...")
                continue
            else:
                update_dict[key] = d[key]

        if not update_dict:
            continue

        updates.append(TaskUpdateRequest(_id=entries[i]["task_id"], **update_dict))

    # # pretty print
    # # add comment to the modified fields
    # updates = [u.model_dump(exclude_unset=True) for u in updates]
    # updates_commented_seq = commented_seq_from_dict_list(updates)
    #

    click.echo_via_pager(
        ls_yaml_format_iter(
            updates,
            exclude_unset=True,
            use_rich=False,
        )
    )


if __name__ == "__main__":
    main()
