import subprocess

import typer

app = typer.Typer()


@app.command()
def send_email(
    recipient: str = typer.Option(
        ...,
        envvar="RECIPIENT",
        help="Recipient email address (defaults to RECIPIENT environment variable)",
    ),
    subject: str = typer.Option(..., prompt=True, help="Email subject"),
    content: str = typer.Option(..., prompt=True, help="Email content"),
):
    """
    Send an email using the system mail command.

    The recipient defaults to the RECIPIENT environment variable if not specified.
    """
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


if __name__ == "__main__":
    app()
