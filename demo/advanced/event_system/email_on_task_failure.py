import subprocess

import typer

from labtasker import connect_events

app = typer.Typer()


def send(
    recipient: str,
    subject: str,
    content: str,
):
    try:
        mail_cmd = ["mail", "-s", subject, recipient]

        process = subprocess.run(
            mail_cmd,
            input=content.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if process.returncode == 0:
            print("Email sent successfully!")
        else:
            error_message = process.stderr.decode().strip()
            print(f"Error sending email: {error_message}")
            raise typer.Exit(process.returncode)
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        raise typer.Exit(1)


@app.command()
def email_on_task_failure(
    recipient: str = typer.Option(
        ...,
        envvar="RECIPIENT",
        help="Recipient email address (defaults to RECIPIENT environment variable)",
    ),
):
    """
    Send an email if received task failed event.

    The recipient defaults to the RECIPIENT environment variable if not specified.
    """
    listener = connect_events()
    print(f"Connected. Client listener ID: {listener.get_client_id()}")
    for event_resp in listener.iter_events():
        if not event_resp.event.type == "state_transition":
            continue

        fsm_event = event_resp.event
        if fsm_event.old_state == "running" and fsm_event.new_state == "failed":
            # running -> failed
            print(f"Task {fsm_event.entity_id} failed. Attempt to send email...")
            send(
                recipient=recipient,
                subject="Task failed",
                content=f"Task {fsm_event.entity_id} failed.",
            )


if __name__ == "__main__":
    app()
