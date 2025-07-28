# How to Filter

!!! abstract
    This page tells you how to use query filter to get tasks you want.

Labtasker provides a versatile query filter mechanism to **list / update / fetch** tasks you want.

It supports:

- Query a specific field of nested dicts
- Query using logical operators and comparison operators (e.g. `>=`, `<=`, `in`, `==`)
- Query using regular expressions (e.g. `regex(task_name, "^[a-z]-\d$")`)
- Query using time and date (e.g. `created_at >= date("3 hours ago")`)

## Syntaxes

Originally, Labtasker filter comes with 2 syntaxes:

1. **Python Native Syntax**: Intuitive to use.
   ```bash
   # Find tasks where args.foo.bar > 0.1
   labtasker task ls -f 'args.foo.bar > 0.1' --quiet --no-pager
   ```
   ==Note:== Does not support `not in`, `not expr`, or `!=` due to null value ambiguities

2. **MongoDB Syntax**: More powerful but requires MongoDB knowledge.
   ```bash
   # Find tasks where args.foo.bar > 0.1
   labtasker task ls -f '{"args.foo.bar": {"$gt": 0.1}}' --quiet --no-pager
   ```

## Typical Use Cases

### Filter by comparison

=== "Task name matching"
    ```bash
    labtasker task ls -f 'task_name == "task_name"'
    ```
=== "Task arg value comparison"
    ```bash
    labtasker task ls -f 'args.foo.bar > 0.1'
    ```
=== "Date time comparison"
    ```bash
    labtasker task ls -f 'created_at >= date("3 hours ago")
    ```

!!! note "Why `!=`, `not in`, `not` is not supported"
    Since database uses Three-Valued Logic, `!=`, `not`, `not in` may result in null value ambiguity. Therefore we forbid such negation operations.

### Filter by logical operators

=== "Logical AND"
    ```bash
    labtasker task ls -f 'args.foo.bar > 0.1 and args.foo.baz < 0.2'
    ```

=== "Logical OR"
    ```bash
    labtasker task ls -f 'args.foo.bar > 0.1 or args.foo.baz < 0.2'
    ```

### Filter by date

Date string parsing is implemented using [dateparser](https://github.com/scrapinghub/dateparser).
You can refer to its documentation for supported syntaxes.

**Note: if UTC is not specified, the time provided will be considered as local time and converted to UTC first before applying query.**

=== "Filter by absolute date"
    ```bash
    labtasker task ls -f 'created_at >= date("Jul 28 11:25")'
    ```
=== "Filter by relative date"
    ```bash
    labtasker task ls -f 'created_at >= date("3 hours ago")'
    ```
=== "Filter by UTC"
    ```bash
    labtasker task ls -f 'created_at >= date("Jul 28 14:47 UTC")'
    ```

For more detailed usage and tests, you can see the code here: https://github.com/luocfprime/labtasker/tree/main/tests/test_client/test_core/test_query_transpiler/test_matching.py
