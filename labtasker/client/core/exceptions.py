import httpx


class LabtaskerError(Exception):
    """Base exception for labtasker"""

    pass


class LabtaskerRuntimeError(RuntimeError, LabtaskerError):
    """General runtime error"""

    pass


class LabtaskerValueError(ValueError, LabtaskerError):
    """General value error"""

    pass


class LabtaskerTypeError(ValueError, LabtaskerError):
    """General type error"""

    pass


class LabtaskerNetworkError(LabtaskerError):
    """General network error"""

    pass


class LabtaskerHTTPStatusError(httpx.HTTPStatusError, LabtaskerNetworkError):
    """HTTPStatusError"""

    pass


class LabtaskerConnectError(httpx.ConnectError, LabtaskerNetworkError):
    pass


class LabtaskerConnectTimeout(httpx.ConnectTimeout, LabtaskerNetworkError):
    pass


class _LabtaskerJobFailed(LabtaskerRuntimeError):
    """An internal exception used by `loop`. Triggered when joh subprocess returned non-zero exit code."""

    pass


class _LabtaskerLoopExit(LabtaskerRuntimeError):
    """An internal exception used by job_runner. Triggered when the loop should exit."""

    pass


class WorkerSuspended(LabtaskerRuntimeError):
    pass


class CmdParserError(LabtaskerError):
    pass


class CmdSyntaxError(SyntaxError, CmdParserError):
    pass


class CmdKeyError(KeyError, CmdParserError):
    pass


class CmdTypeError(TypeError, CmdParserError):
    pass


class QueryTranspilerError(LabtaskerError):
    pass


class QueryTranspilerSyntaxError(SyntaxError, QueryTranspilerError):
    pass


class QueryTranspilerValueError(ValueError, QueryTranspilerError):
    pass
