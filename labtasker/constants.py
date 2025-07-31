from enum import Enum


class Priority(int, Enum):
    LOW = 0
    MEDIUM = 10  # default
    HIGH = 20


DOT_SEPARATED_KEY_PATTERN = r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$"
