"""
Borrowed from https://github.com/pallets/click/blob/a8b41c077b225c30921a78190507a463a20ebb1b/src/click/_termui_impl.py
Hacked pager so that it does not check isatty when displaying results.
Used for cascaded CLI commands where a pager is used at last to display results.

Original Click License:
Copyright 2014 Pallets

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1.  Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

2.  Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.

3.  Neither the name of the copyright holder nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import inspect
import itertools

from click._termui_impl import *  # noqa: F403
from click._termui_impl import _nullpager, _pipepager, _tempfilepager
from click.globals import resolve_color_default


def pager_no_check_isatty(
    generator: cabc.Iterable[str], color: bool | None = None
) -> None:
    """Decide what method to use for paging through text."""
    stdout = sys.stdout

    # There are no standard streams attached to write to. For example,
    # pythonw on Windows.
    if stdout is None:
        stdout = StringIO()

    # if not isatty(sys.stdin) or not isatty(stdout):
    #     return _nullpager(stdout, generator, color)

    # Split and normalize the pager command into parts.
    pager_cmd_parts = shlex.split(os.environ.get("PAGER", ""), posix=False)
    if pager_cmd_parts:
        if WIN:
            if _tempfilepager(generator, pager_cmd_parts, color):
                return
        elif _pipepager(generator, pager_cmd_parts, color):
            return

    if os.environ.get("TERM") in ("dumb", "emacs"):
        return _nullpager(stdout, generator, color)
    if (WIN or sys.platform.startswith("os2")) and _tempfilepager(
        generator, ["more"], color
    ):
        return
    if _pipepager(generator, ["less"], color):
        return

    import tempfile

    fd, filename = tempfile.mkstemp()
    os.close(fd)
    try:
        if _pipepager(generator, ["more"], color):
            return
        return _nullpager(stdout, generator, color)
    finally:
        os.unlink(filename)


def echo_via_pager_no_check_isatty(
    text_or_generator: cabc.Iterable[str] | t.Callable[[], cabc.Iterable[str]] | str,
    color: bool | None = None,
) -> None:
    """
    Borrowed from https://github.com/pallets/click/blob/a8b41c077b225c30921a78190507a463a20ebb1b/src/click/termui.py#L255

    This function takes a text and shows it via an environment specific
    pager on stdout.

    .. versionchanged:: 3.0
       Added the `color` flag.

    :param text_or_generator: the text to page, or alternatively, a
                              generator emitting the text to page.
    :param color: controls if the pager supports ANSI colors or not.  The
                  default is autodetection.
    """
    color = resolve_color_default(color)

    if inspect.isgeneratorfunction(text_or_generator):
        i = t.cast("t.Callable[[], cabc.Iterable[str]]", text_or_generator)()
    elif isinstance(text_or_generator, str):
        i = [text_or_generator]
    else:
        i = iter(t.cast("cabc.Iterable[str]", text_or_generator))

    # convert every element of i to a text type if necessary
    text_generator = (el if isinstance(el, str) else str(el) for el in i)

    return pager_no_check_isatty(itertools.chain(text_generator, "\n"), color)
