"""
This module contains examples of various datetime.now() usage patterns
that should be detected by the datetime_now_checker.py script.
"""

# Pattern 1: Standard import
import datetime  # noqa


def pattern1():
    # Direct datetime.now() call
    current_time = datetime.now()
    return current_time


# Pattern 2: Full module path


def pattern2():
    # Full module path
    current_time = datetime.datetime.now()
    return current_time


# Pattern 3: Direct datetime class import


def pattern3():
    # Direct class import
    current_time = datetime.now()
    return current_time


# Pattern 4: Import with alias
import datetime as dt


def pattern4():
    # Aliased module
    current_time = dt.datetime.now()
    return current_time


# Pattern 5: From import
from datetime import datetime


def pattern5():
    # From import
    current_time = datetime.now()
    return current_time


from datetime import datetime


def pattern6():
    # With parameters
    current_time = datetime.now(tz=None)
    return current_time


def pattern7():
    # utcnow usage
    current_time = datetime.utcnow()
    return current_time


def pattern8():
    # Full path utcnow
    current_time = datetime.datetime.utcnow()
    return current_time


# Pattern 9: Method chaining
def pattern9():
    # Method chaining with now()
    formatted_time = datetime.now().strftime("%Y-%m-%d")
    return formatted_time


# Pattern 10: Aliased import with utcnow
def pattern10():
    # Aliased import with utcnow
    current_time = dt.utcnow()
    return current_time


# Pattern 11: From import with utcnow
from datetime import datetime as dt2


def pattern11():
    # From import with alias and utcnow
    current_time = dt2.utcnow()
    return current_time


# Pattern 12: Assignment to variable first
def pattern12():
    # Assign datetime to variable first
    dt_module = datetime.datetime
    current_time = dt_module.now()
    return current_time


# Pattern 13: Using in a class method
class TimeClass:
    def get_current_time(self):
        return datetime.datetime.now()


# Pattern 14: Using in a lambda
def pattern14():
    get_time = lambda: datetime.now()  # noqa
    return get_time()


# Pattern 15: Using in a list comprehension
def pattern15():
    return [datetime.now() for _ in range(3)]


# Pattern 16: Using in a nested function
def pattern16():
    def inner_func():
        return datetime.datetime.now()

    return inner_func()
