import sys
import os
import json
import inquirer


def safe_prompt(questions):
    try:
        answers = inquirer.prompt(questions)
        if answers is None:
            sys.exit(1)
        return answers
    except KeyboardInterrupt:
        print("\nOperation cancelled. Exiting.")
        sys.exit(1)


def load_input_file(path):
    if not os.path.isfile(path):
        print(f"Error: Input file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r") as f:
        content = f.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            print("Error: PyYAML is required for YAML input files. Install with: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        return yaml.safe_load(content) or {}
    return json.loads(content)


def merge_inputs(cli_args, input_data):
    result = {}
    if input_data:
        result.update(input_data)
    if cli_args:
        for key, val in vars(cli_args).items():
            if val is not None and key not in ("command", "input_file"):
                result[key] = val
    return result
