from ast import literal_eval
from typing import Any, Dict, Optional

import typer


def parse_metadata(metadata: str) -> Optional[Dict[str, Any]]:
    """
    Parse metadata string into a dictionary.
    Raise typer.BadParameter if the input is invalid.
    """
    if not metadata:
        return None
    try:
        parsed = literal_eval(metadata)
        if not isinstance(parsed, dict):
            raise ValueError("Metadata must be a dictionary.")
        return parsed
    except (ValueError, SyntaxError) as e:
        raise typer.BadParameter(f"Invalid metadata: {e}")
