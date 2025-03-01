import typer
from fastapi import HTTPException

from labtasker.filtering import (
    filter_exception,
    register_sensitive_text,
    set_traceback_filter_hook,
)

app = typer.Typer()

dummy_password = "mypassword"
register_sensitive_text(dummy_password)

set_traceback_filter_hook(enabled=True)  # enable by default


def raise_single_exception_no_protection():
    # disable hook to achieve "no protection"
    set_traceback_filter_hook(enabled=False)
    raise Exception(f"password={dummy_password}")


def raise_single_exception():
    raise Exception(f"password={dummy_password}")


def raise_chained_exception():
    try:
        raise_single_exception()
    except Exception as e:
        raise Exception(f"chained: password={dummy_password}") from e


def raise_with_ctx_manager():
    # disable hooks first, to only test the filter_exception context manager
    set_traceback_filter_hook(enabled=False)
    with filter_exception():
        raise_chained_exception()


@filter_exception()
def raise_with_decorator():
    # disable hooks first, to only test the filter_exception context manager
    set_traceback_filter_hook(enabled=False)

    raise_chained_exception()


def raise_fastapi_http_exception():
    raise HTTPException(status_code=500, detail=f"password={dummy_password}")


@app.command()
def typer_single_exception():
    raise_single_exception()


@app.command()
def typer_chained_exception():
    raise_chained_exception()


@app.command()
def typer_fastapi_http_exception():
    raise_fastapi_http_exception()


def main():
    return typer.main.get_command(app)()


if __name__ == "__main__":
    main()
