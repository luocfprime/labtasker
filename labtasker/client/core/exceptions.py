import httpx


class LabtaskerError(Exception):
    """Base exception for labtasker"""

    pass


class LabtaskerRuntimeError(LabtaskerError, RuntimeError):
    """General runtime error"""

    pass


class LabtaskerValueError(LabtaskerError, ValueError):
    """General value error"""

    pass


class LabtaskerTypeError(LabtaskerError, ValueError):
    """General type error"""

    pass


class LabtaskerNetworkError(LabtaskerError):
    """General network error"""

    pass


class LabtaskerHTTPStatusError(LabtaskerNetworkError, httpx.HTTPStatusError):
    """HTTPStatusError"""

    pass


class LabtaskerConnectError(LabtaskerNetworkError, httpx.ConnectError):
    pass


class WorkerSuspended(LabtaskerRuntimeError):
    pass


class CmdParserError(LabtaskerError):
    pass


class CmdSyntaxError(CmdParserError):
    pass


class CmdKeyError(CmdParserError, KeyError):
    pass


class CmdTypeError(CmdParserError, TypeError):
    pass
