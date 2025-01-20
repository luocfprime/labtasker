import sys

from lark import Lark, Transformer

# Define the grammar for detecting sensitive patterns
grammar = r"""
    start: (line | sensitive_pattern | blank_line)*

    line: WS? NON_SENSITIVE_TEXT NEWLINE?
    sensitive_pattern: WS? KEYWORD WS? ASSIGN WS? VALUE NEWLINE?
    blank_line: WS? NEWLINE?

    KEYWORD: /(?i)password/
    ASSIGN: /[=:]/
    VALUE: ( QUOTED_VALUE | UNQUOTED_VALUE )
    QUOTED_VALUE: /(\"[^\"]*\")|(\'[^\']*\')/
    UNQUOTED_VALUE: /[^\s\n]+/
    WS: /[ \t]+/
    NON_SENSITIVE_TEXT: /[^\n]+/
    NEWLINE: /\n/

    %import common.WS -> WHITESPACE
"""


class SanitizeTransformer(Transformer):
    def sensitive_pattern(self, args):
        return "*****\n"

    def line(self, args):
        text = "".join(str(arg) for arg in args)
        if any(sensitive in text.lower() for sensitive in ["password", "secret"]):
            return "*****\n"
        return text

    def blank_line(self, args):
        return "".join(str(arg) for arg in args) if args else "\n"

    def start(self, args):
        return "".join(str(arg) for arg in args)


def sanitize_text(text):
    if not isinstance(text, str):
        return ""

    try:
        parser = Lark(grammar, parser="lalr", transformer=SanitizeTransformer())
        return parser.parse(text)
    except Exception:
        # Fallback: basic sanitization if parsing fails
        lines = text.split("\n")
        sanitized_lines = []
        for line in lines:
            if any(sensitive in line.lower() for sensitive in ["password", "secret"]):
                sanitized_lines.append("*****")
            else:
                sanitized_lines.append(line)
        return "\n".join(sanitized_lines)


def install_traceback_filter():
    """Install a system-wide traceback filter for sensitive information"""
    original_excepthook = sys.excepthook

    def filtered_excepthook(exc_type, exc_value, exc_tb):
        sanitized_msg = sanitize_text(str(exc_value))
        sanitized_exc = exc_type(sanitized_msg)

        original_excepthook(exc_type, sanitized_exc, exc_tb)

    sys.excepthook = filtered_excepthook


install_traceback_filter()
