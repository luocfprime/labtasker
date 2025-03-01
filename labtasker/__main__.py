"""Entrypoint for the cli app"""

import typer

from labtasker.client.cli import app


def main():
    return typer.main.get_command(app)()


if __name__ == "__main__":
    main()
