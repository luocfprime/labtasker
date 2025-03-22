"""
Event related commands.
"""

from functools import wraps
from typing import Callable, List, Optional, Tuple, Union

import typer
from rich.console import Group
from rich.panel import Panel
from rich.style import StyleType
from rich.table import Table
from rich.text import Text

from labtasker.api_models import EventResponse, StateTransitionEvent
from labtasker.client.core.cli_utils import cli_utils_decorator
from labtasker.client.core.events import connect_events
from labtasker.client.core.logging import set_verbose, stdout_console, verbose_print

app = typer.Typer()


STATE_COLORS = {
    # task states
    "pending": "gold1",
    "running": "dodger_blue1",
    "success": "green3",
    "failed": "red1",
    "cancelled": "white",
    # worker states
    "active": "green3",
    "suspended": "white",
    "crashed": "red1",
}

# Event renderer registry - maps event types to their rendering functions
EVENT_RENDERERS = {}

# Define compact event renderers for different event types
COMPACT_EVENT_RENDERERS = {}


def event_renderer(event_type: str):
    """Decorator to register event renderers by event type."""

    def decorator(func: Callable[[EventResponse], None]):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        EVENT_RENDERERS[event_type] = wrapper
        return wrapper

    return decorator


def compact_event_renderer(event_type: str):
    """Decorator to register compact event renderers by event type."""

    def decorator(func: Callable[[EventResponse], Optional[List[Text]]]):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        COMPACT_EVENT_RENDERERS[event_type] = wrapper
        return wrapper

    return decorator


def render_event(event: EventResponse) -> None:
    """Render an event with rich formatting based on its type."""
    # Get the appropriate renderer for this event type
    renderer = EVENT_RENDERERS.get(event.event.type, render_generic_event)
    renderer(event)


def render_generic_event(event: EventResponse) -> None:
    """Generic renderer for event types without a specific renderer."""
    table = Table(show_header=False, box=None)
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    table.add_row("Sequence", str(event.sequence))
    table.add_row("Timestamp", event.timestamp.isoformat())
    table.add_row("Type", event.event.type)

    # Add any other fields from the event
    for key, value in event.event.model_dump().items():
        if key not in ["type", "queue_id", "timestamp", "metadata"]:
            table.add_row(key, str(value))

    panel = Panel(
        table,
        title=f"Event {event.sequence}",
        border_style="blue",
    )
    stdout_console.print(panel)


def render_compact_event(event: EventResponse) -> None:
    """Render event in compact format."""
    # Common fields for all event types
    out = [
        Text(f"[{event.sequence:5}]"),
        Text(f"[{event.timestamp.isoformat()}]"),
        Text(f"[{event.event.type:20}]"),
    ]

    # Use registered renderer for this event type if available
    renderer = COMPACT_EVENT_RENDERERS.get(event.event.type)
    if renderer:
        additional_text = renderer(event)
        if additional_text:
            out.extend(additional_text)

    stdout_console.print(Text.assemble(*out))


@event_renderer("state_transition")
def render_state_transition_event(event_resp: EventResponse) -> None:
    """Render a state transition event with rich formatting."""
    fsm_event: StateTransitionEvent = event_resp.event
    entity_type = fsm_event.entity_type.capitalize()
    new_state = fsm_event.new_state

    # Create main info table
    info_table = Table(show_header=False, box=None)
    info_table.add_column("Property", style="cyan")
    info_table.add_column("Value")

    info_table.add_row("Sequence", str(event_resp.sequence))
    info_table.add_row("Timestamp", event_resp.timestamp.isoformat())
    info_table.add_row("Entity Type", entity_type)
    info_table.add_row("Entity ID", fsm_event.entity_id)

    # Create state transition display
    state_table = Table(show_header=False, box=None)
    state_table.add_column("From", style="yellow")
    state_table.add_column("To", style=STATE_COLORS.get(new_state, "blue"))
    state_table.add_row(fsm_event.old_state, new_state)

    # Group the components
    group = Group(info_table, Text("State Transition:", style="bold"), state_table)

    # Create panel with appropriate styling
    panel = Panel(
        group,
        title=f"{entity_type} State Change",
        border_style=STATE_COLORS.get(new_state, "blue"),
    )

    stdout_console.print(panel)


@compact_event_renderer("state_transition")
def compact_state_transition(
    event_resp: EventResponse,
) -> List[Union[str, "Text", Tuple[str, StyleType]],]:
    """Compact renderer for state transition events."""
    fsm_event: StateTransitionEvent = event_resp.event
    old_state = fsm_event.old_state
    new_state = fsm_event.new_state

    return [
        Text(f"[{fsm_event.entity_type:10}]"),
        Text(f"[{fsm_event.entity_id:10}]"),
        Text(
            f"[{old_state:10} -> {new_state:10}]",
            style=STATE_COLORS.get(new_state, "blue"),
        ),
    ]


@app.command()
@cli_utils_decorator
def listen(
    timeout: int = typer.Option(
        10,
        "--timeout",
        help="Connection timeout in seconds when establishing the initial connection.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed event information for debugging.",
        callback=set_verbose,
        is_eager=True,
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Display raw Server-Sent Events (SSE) data instead of formatted output.",
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        "-c",
        help="Use a condensed single-line format for each event.",
    ),
):
    """Monitor real-time events from the Labtasker server.

    This command establishes a persistent connection to the server and displays
    events as they occur, such as:
    - Task state changes (pending → running → success/failed)
    - Worker state changes (active → suspended → crashed)

    Use Ctrl+C to stop listening.
    """
    stdout_console.print("Attempting to connect to server...")
    listener = connect_events(timeout=timeout)
    stdout_console.print(f"Connected. Client listener ID: {listener.get_client_id()}")

    if raw:
        # Raw SSE output mode
        for sse in listener.iter_raw_sse():
            stdout_console.print(sse)
    else:
        # Processed events output mode
        for event in listener.iter_events():
            if compact:
                render_compact_event(event)
            else:
                render_event(event)

            verbose_print(event.model_dump_json(indent=4))
