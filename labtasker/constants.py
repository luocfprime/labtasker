from enum import Enum


class Priority(int, Enum):
    LOW = 0
    MEDIUM = 10  # default
    HIGH = 20
