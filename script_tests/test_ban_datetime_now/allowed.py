"""
This module contains examples of allowed datetime usage
that should NOT be detected by the datetime_now_checker.py script.
"""

import datetime  # noqa

# Pattern 1: Using other datetime functionality


def pattern1():
    # Creating a datetime object manually is allowed
    current_time = datetime.datetime(2023, 3, 15, 12, 30, 0)
    return current_time


# Pattern 2: Using date functionality


def pattern2():
    # Using date is allowed
    today = datetime.date.today()
    return today


# Pattern 3: Using timedelta
from datetime import timedelta


def pattern3():
    # Using timedelta is allowed
    one_day = timedelta(days=1)
    return one_day


# Pattern 4: Using datetime constants/attributes


def pattern4():
    # Using min/max attributes is allowed
    min_datetime = datetime.datetime.min
    return min_datetime


# Pattern 5: Parsing datetime strings


def pattern5():
    # Parsing datetimes is allowed
    parsed_date = datetime.strptime("2023-03-15", "%Y-%m-%d")
    return parsed_date


# Pattern 6: Creating custom datetime
import datetime


def pattern6():
    # Using the constructor is allowed
    custom_dt = datetime.datetime(year=2023, month=3, day=15, hour=12, minute=30)
    return custom_dt


# Pattern 7: Using datetime in type hints
from datetime import datetime


def pattern7(dt: datetime) -> datetime:
    # Using datetime as a type hint is allowed
    return dt


# Pattern 8: Subclassing datetime
from datetime import datetime


class CustomDatetime(datetime):
    # Subclassing datetime is allowed
    def is_weekend(self):
        return self.weekday() >= 5
