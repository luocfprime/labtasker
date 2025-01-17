from functools import wraps
from typing import Any, Dict

from fastapi import HTTPException
from pydantic import ValidationError, validate_call
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

from labtasker.utils import flatten_dict


def validate_arg(func):
    """Wrap around Pydantic `validate_call` to yield HTTP_400_BAD_REQUEST"""

    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return validate_call(func)(*args, **kwargs)
        except ValidationError as e:
            # Catch Pydantic validation errors and re-raise them as HTTP 400
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=e.errors(),  # Provide detailed validation errors
            ) from e
        except HTTPException:
            # Allow pre-existing HTTPExceptions to propagate
            raise
        except Exception as e:
            # Catch any other exception and raise it as a generic HTTP 500 error
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            ) from e

    return wrapped


def query_dict_to_mongo_filter(query_dict, parent_key=""):
    mongo_filter = {}

    flattened_query = flatten_dict(query_dict, parent_key=parent_key)
    for full_key in flattened_query.keys():
        mongo_filter[full_key] = {"$exists": True}

    return mongo_filter


def merge_filter(*filters, logical_op="and"):
    """
    Merge multiple MongoDB filters using a specified logical operator, while ignoring empty filters.

    Args:
        *filters: Arbitrary number of filter dictionaries to merge.
        logical_op (str): The logical operator to use for merging filters.
                          Must be one of "and", "or", or "nor".

    Returns:
        dict: A MongoDB query filter with the specified logical operator applied.

    Raises:
        HTTPException: If the logical_op is not valid.
    """
    if logical_op not in ["and", "or", "nor"]:
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid logical operator: {logical_op}. Must be 'and', 'or', or 'nor'.",
        )

    valid_filters = [
        f for f in filters if f
    ]  # Filters out None, {}, or other falsy values

    # If no valid filters remain, return an empty filter
    if not valid_filters:
        return {}

    if len(valid_filters) == 1:
        return valid_filters[0]

    mongo_logical_op = f"${logical_op}"  # "$and", "$or", "$nor"

    return {mongo_logical_op: valid_filters}


def sanitize_query(queue_id: str, query: Dict[str, Any]) -> Dict[str, Any]:
    """Enforce only query on queue_id specified in query"""
    return {
        "$and": [
            {"queue_id": queue_id},  # Enforce queue_id
            query,  # Existing user query
        ]
    }
