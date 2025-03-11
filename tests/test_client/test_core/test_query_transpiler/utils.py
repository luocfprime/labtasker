from copy import deepcopy


def are_filters_equivalent(filter1, filter2):
    """
    Analytically determines if two MongoDB filters are logically equivalent.

    Args:
        filter1: First MongoDB filter dict
        filter2: Second MongoDB filter dict

    Returns:
        bool: True if filters are equivalent, False otherwise
    """
    # Normalize the filters
    normalized1 = normalize_filter(filter1)
    normalized2 = normalize_filter(filter2)

    # Compare the normalized filters
    return normalized1 == normalized2


def normalize_filter(filter_dict):
    """
    Normalizes a MongoDB filter to a canonical form for comparison.

    Only sorts elements in permutation-invariant operations (like $and, $or).
    Relies on Python's built-in dictionary comparison for the rest.

    Args:
        filter_dict: MongoDB filter dict

    Returns:
        Normalized filter dict
    """
    if not filter_dict:
        return {}

    # Make a deep copy to avoid modifying the original
    filter_dict = deepcopy(filter_dict)

    # Define permutation-invariant operators
    # These are operations where order of elements doesn't matter
    # Example: {$and: [{a: 1}, {b: 2}]} is equivalent to {$and: [{b: 2}, {a: 1}]}
    permutation_invariant_ops = ["$and", "$or", "$nor", "$in", "$nin", "$all"]

    if isinstance(filter_dict, dict):
        result = {}

        for key, value in filter_dict.items():
            # Handle permutation-invariant operators with list values
            if key in permutation_invariant_ops and isinstance(value, list):
                # Normalize each element in the list and sort them
                # Example: {$and: [{a: 1}, {b: 2}]} -> {$and: [{a: 1}, {b: 2}]} (sorted)
                result[key] = sorted(
                    [normalize_filter(item) for item in value], key=lambda x: str(x)
                )
            # Handle nested documents and other operators
            elif isinstance(value, dict):
                # Recursively normalize nested dictionaries
                # Example: {field: {$gt: 5, $lt: 10}} or {nested: {field1: value1}}
                result[key] = normalize_filter(value)
            # Handle lists that aren't direct values of permutation-invariant operators
            elif isinstance(value, list):
                # Check if list contains dictionaries that need normalization
                if any(isinstance(item, dict) for item in value):
                    # Normalize any dictionaries in the list without changing the order in the list
                    # Example: {field: [{a: 1}, {b: 2}]}
                    result[key] = [
                        normalize_filter(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    # Simple list values - preserve as is
                    # Example: {field: [1, 2, 3]}
                    result[key] = value
            else:
                # Simple scalar values - preserve as is
                # Example: {field: "value"}
                result[key] = value

        return result

    # Handle list of conditions (implicit $and)
    # These are permutation-invariant
    # Example: [{a: 1}, {b: 2}]
    elif isinstance(filter_dict, list):
        return sorted(
            [normalize_filter(item) for item in filter_dict], key=lambda x: str(x)
        )

    return filter_dict


def normalize_expression(expr):
    """
    Normalize MongoDB $expr operators, focusing only on permutation-invariant operators

    Args:
        expr: MongoDB expression

    Returns:
        Normalized expression
    """
    # Define permutation-invariant operators in expressions
    permutation_invariant_ops = ["$and", "$or", "$nor"]

    if isinstance(expr, dict):
        result = {}

        for key, value in expr.items():
            # For permutation-invariant operators with list values, sort them
            if key in permutation_invariant_ops and isinstance(value, list):
                # Example: {$and: [{$gt: ["$price", 10]}, {$lt: ["$qty", 20]}]}
                result[key] = sorted(
                    [normalize_expression(item) for item in value], key=lambda x: str(x)
                )
            # For other operators with dictionary or list values, recurse
            elif isinstance(value, dict):
                result[key] = normalize_expression(value)
            elif isinstance(value, list):
                result[key] = [
                    normalize_expression(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value

        return result
    elif isinstance(expr, list):
        return [
            normalize_expression(item) if isinstance(item, dict) else item
            for item in expr
        ]
    else:
        return expr
