import ast
import json
import sys


def main():
    lines = sys.stdin.readlines()

    try:
        json.loads(lines[0])
    except json.JSONDecodeError:
        print("Error: First line is not a valid JSON.", file=sys.stderr)
        sys.exit(1)

    print(lines[0].strip("\n"))

    first_timestamp = None

    for i, line in enumerate(lines[1:], start=1):
        try:
            data = ast.literal_eval(line)
            if (
                isinstance(data, list)
                and len(data) > 0
                and isinstance(data[0], (int, float))
            ):
                if first_timestamp is None:
                    first_timestamp = data[0]
                data[0] -= first_timestamp
                print(json.dumps(data))
            else:
                print(line.strip())
        except (ValueError, SyntaxError):
            print(line.strip())


if __name__ == "__main__":
    main()
