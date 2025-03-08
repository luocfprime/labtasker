from enum import Enum


class Priority(int, Enum):
    LOW = 0
    MEDIUM = 10  # default
    HIGH = 20


KEY_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_-]*$"  # start with letter or underscore
DOT_SEPARATED_KEY_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_-]*(\.[a-zA-Z_][a-zA-Z0-9_-]*)*$"
