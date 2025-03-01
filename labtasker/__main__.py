"""Entrypoint for the cli app"""

import typer

from labtasker.client.cli import app


def main():
    # Use this to invoke command to prevent typer overriding exception hook
    return typer.main.get_command(app).main()


if __name__ == "__main__":
    main()
