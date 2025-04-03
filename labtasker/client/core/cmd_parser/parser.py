import os
from typing import Any, Dict, List, Set, Tuple, Union

from rich import print
from rich.console import Console
from rich.text import Text

from labtasker.client.core.cmd_parser.generated.LabCmd import LabCmd
from labtasker.client.core.cmd_parser.generated.LabCmdLexer import LabCmdLexer
from labtasker.client.core.cmd_parser.generated.LabCmdListener import LabCmdListener
from labtasker.client.core.exceptions import (
    CmdKeyError,
    CmdParserError,
    CmdSyntaxError,
    CmdTypeError,
)
from labtasker.client.core.logging import stderr_console
from labtasker.vendor.antlr4 import (
    CommonTokenStream,
    InputStream,
    ParserRuleContext,
    ParseTreeWalker,
)
from labtasker.vendor.antlr4.error.ErrorListener import ErrorListener

# Posix quote and windows quote
if os.name == "nt":
    import mslex

    quote = mslex.quote
else:
    import shlex

    quote = shlex.quote

_debug_print = False


def reverse_quotes(s: str) -> str:
    return "".join(['"' if char == "'" else "'" if char == '"' else char for char in s])


def print_tab(content, ctx, tabs):
    print("\t" * tabs + content + "\t" * (5 - tabs) + ctx)


def enter_debug(func):
    def wrapper(self, *args, **kwargs):
        if _debug_print:
            # Extract the context text for logging
            ctx_text = args[0].getText() if args else ""
            # Print entering message with current indentation
            print_tab(
                f"Entering {func.__name__}",
                f">>>> '{ctx_text}'",
                getattr(self, "tabs", 0),
            )
            # Increment tabs for nested indentation
            setattr(self, "tabs", getattr(self, "tabs", 0) + 1)  # self.tabs += 1
        # Execute the original method
        return func(self, *args, **kwargs)

    return wrapper


def exit_debug(func):
    def wrapper(self, *args, **kwargs):
        if _debug_print:
            # Decrement tabs before exiting
            setattr(self, "tabs", getattr(self, "tabs", 0) - 1)  # self.tabs -= 1
            # Extract the context text for logging
            ctx_text = args[0].getText() if args else ""
            # Print exiting message with updated indentation
            print_tab(
                f"Exiting {func.__name__}",
                f"<<<< '{ctx_text}'",
                getattr(self, "tabs", 0),
            )
        # Execute the original method
        return func(self, *args, **kwargs)

    return wrapper


def get_line_from_ctx(ctx: ParserRuleContext) -> str:
    line = ctx.start.line
    char_stream = ctx.start.getInputStream()
    full_text = char_stream.getText(0, char_stream.size)
    lines = full_text.splitlines()
    if 1 <= line <= len(lines):
        current_line_content = lines[line - 1]
    else:
        current_line_content = "<unknown line>"
    return current_line_content


def format_print_error(
    console: Console,
    line: int,
    column: int,
    error_line: str,
    msg: str,
    context_size: int = 50,
) -> None:
    """
    Format and print an error message with context using Rich for enhanced terminal output.

    Args:
        console (Console): The Rich console instance for output.
        line (int): The line number where the error occurred.
        column (int): The column number where the error occurred.
        error_line (str): The complete line of text containing the error.
        msg (str): The error message to display.
        context_size (int, optional): Number of characters to show around the error. Defaults to 50.
    """
    # Determine the start and end positions for the context
    start = max(0, column - context_size)  # Ensure start is non-negative
    end = min(
        len(error_line), column + context_size + 1
    )  # Ensure end doesn't exceed line length

    # Extract the context line
    context_line = error_line[start:end]

    # Add ellipses to indicate truncation
    if start > 0:
        context_line = f"...{context_line}"  # Add "..." at the beginning if truncated
    if end < len(error_line):
        context_line = f"{context_line}..."  # Add "..." at the end if truncated

    # Calculate pointer offset for the truncated context
    pointer_offset = (
        column - start + (3 if start > 0 else 0)
    )  # Adjust for "..." at the start
    pointer = " " * pointer_offset + "^"

    # Use Rich's Text objects instead of f-strings to avoid markup parsing issues
    error_title = Text(
        f"Error when parsing cmd line at line {line}, column {column + 1}:",
        style="bold red",
    )

    context_header = Text("Err context: ", style="bold orange1")
    context_content = Text(context_line)
    context_line_display = Text.assemble(context_header, context_content)

    pointer_line = Text(
        f"{' ' * len(context_header)}{pointer}  <-- Error here (Column: {column + 1})"
    )
    pointer_line.stylize("bright_red", pointer_offset + 11, pointer_offset + 12)
    pointer_line.stylize("bold red", pointer_offset + 15, len(pointer_line))

    error_msg_header = Text("Error: ", style="bold red")
    error_msg_content = Text(msg)
    error_msg_display = Text.assemble(error_msg_header, error_msg_content)

    # Print the complete error message
    console.print(error_title)
    console.print(context_line_display)
    console.print(pointer_line)
    console.print(error_msg_display)
    console.print()  # Add a blank line for better readability


class CmdListener(LabCmdListener):
    def __init__(self, variable_table, use_quote: bool):
        super().__init__()
        self.variable_table = variable_table
        self.use_quote = use_quote

        self.result_str = ""
        self.args = set()
        self.variable = None

    # Enter a parse tree produced by LabCmd#command.
    @enter_debug
    def enterCommand(self, ctx: LabCmd.CommandContext):
        if ctx.exception is not None:
            raise RuntimeError(f"Error encountered: {ctx.exception}")

    # Exit a parse tree produced by LabCmd#command.
    @exit_debug
    def exitCommand(self, ctx: LabCmd.CommandContext):
        pass

    # Enter a parse tree produced by LabCmd#variable.
    @enter_debug
    def enterVariable(self, ctx: LabCmd.VariableContext):
        pass

    # Exit a parse tree produced by LabCmd#variable.
    @exit_debug
    def exitVariable(self, ctx: LabCmd.VariableContext):
        if self.variable is None:
            raise RuntimeError(f"Variable not found in context: {ctx.getText()}")

        if isinstance(self.variable, dict):
            # convert dict into bash string
            # reverse quotes simplifies the conventional Python string representation
            if self.use_quote:
                self.result_str += quote(reverse_quotes(str(self.variable)))
            else:
                self.result_str += reverse_quotes(str(self.variable))
        else:
            self.result_str += (
                quote(str(self.variable)) if self.use_quote else str(self.variable)
            )

        self.variable = None

    def enterArgumentList(self, ctx: LabCmd.ArgumentListContext):
        self.args.add(str(ctx.getText()))

    # Enter a parse tree produced by LabCmd#argument.
    @enter_debug
    def enterArgument(self, ctx: LabCmd.ArgumentContext):
        if self.variable is None:
            self.variable = self.variable_table

        try:
            v = self.variable.get(ctx.getText())
            if v is None:
                msg = f"Key '{ctx.getText()}' not found in the current context {self.variable}"

                format_print_error(
                    console=stderr_console,
                    line=ctx.start.line,
                    column=ctx.start.column,
                    error_line=get_line_from_ctx(ctx),
                    msg=msg,
                )
                raise CmdKeyError(msg)
            self.variable = v
        except AttributeError as e:
            msg = f"Expected a dictionary-like object, but got '{type(self.variable).__name__}' for context '{ctx.getText()}'."
            format_print_error(
                console=stderr_console,
                line=ctx.start.line,
                column=ctx.start.column,
                error_line=get_line_from_ctx(ctx),
                msg=msg,
            )
            raise CmdTypeError(msg) from e

    # Exit a parse tree produced by LabCmd#argument.
    @exit_debug
    def exitArgument(self, ctx: LabCmd.ArgumentContext):
        pass

    # Enter a parse tree produced by LabCmd#text.
    @enter_debug
    def enterText(self, ctx: LabCmd.TextContext):
        pass

    # Exit a parse tree produced by LabCmd#text.
    @exit_debug
    def exitText(self, ctx: LabCmd.TextContext):
        self.result_str += ctx.getText()


class CustomErrorListener(ErrorListener):
    def __init__(self, input_text):
        super().__init__()
        self.input_text = input_text.splitlines()

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        # Fetch the offending line
        error_line = (
            self.input_text[line - 1] if 1 <= line <= len(self.input_text) else ""
        )

        format_print_error(stderr_console, line, column, error_line, msg)

        raise CmdSyntaxError(msg)


def cmd_interpolate(
    cmd: Union[List[str], str], variable_table: Dict[str, Any]
) -> Tuple[Union[List[str], str], Set[str]]:
    """
    Interpolate the command string %(...) with the given variable table.

    Notes:
        When cmd is a list of str, it will interpolate each str in the list and return a list of str.
        The behavior is somewhat broken on Windows if the command contains quotes. Therefore, it is recommended to input list of str only.

    Args:
        cmd:
        variable_table:

    Returns:

    """
    if isinstance(cmd, str):
        return interpolate_str(cmd, variable_table)
    else:
        # cmd is a list of str
        interpolated_cmd = []
        involved_keys = set()
        for c in cmd:
            interpolated_str, keys = interpolate_str(c, variable_table, use_quote=False)
            interpolated_cmd.append(interpolated_str)
            involved_keys.update(keys)

        return interpolated_cmd, involved_keys


def interpolate_str(
    input_str: str, variable_table: Dict[str, Any], use_quote: bool = True
) -> Tuple[str, Set[str]]:
    """

    Args:
        input_str:
        variable_table:
        use_quote: quote dict or strings using shlex.quote

    Returns:
        interpolated str, involved keys
    """
    # Parse the input string
    input_stream = InputStream(input_str)
    lexer = LabCmdLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = LabCmd(token_stream)

    # Remove default error listeners and add custom error listener
    parser.removeErrorListeners()
    parser.addErrorListener(CustomErrorListener(input_str))

    try:
        tree = parser.command()
        # Walk the parse tree with the custom listener
        listener = CmdListener(variable_table=variable_table, use_quote=use_quote)
        walker = ParseTreeWalker()
        walker.walk(listener, tree)
    except CmdParserError as e:
        # cast to
        raise e.with_traceback(
            None
        )  # stop deep trace, since msg is handled with format_print_error

    return listener.result_str, listener.args


# def main():
#     input_str = (
#         "python train.py --arg1 %( a.b ) --arg2 %(c.d.e) --arg3 %(arg3) %( a .e) %( a )"
#     )
#     # input_str = "python train.py --arg1 %( { a.b ) --arg2 %(c.d.e) --arg3 %(arg3) %( a .e) %( a )"
#     # input_str = "python train.py --arg1 %( a.b ) --arg2 %(c.d.e) --arg3 %(arg3) %( a .e) %( a )"
#
#     variable_table = {
#         "a": {"b": "value1", "e": "fcc"},
#         "arg3": "e3",
#         "c": {"d": {"e": "value2", "f": "value3"}},
#         "e": [1, 2, 3],
#     }
#
#     output_str = cmd_interpolate(input_str, variable_table)
#     print("table:\t", variable_table)
#     print("Input:\t", input_str)
#     print("Output:\t", output_str)
#
#
# # Example usage
# if __name__ == "__main__":
#     main()
