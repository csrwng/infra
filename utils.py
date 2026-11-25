import sys
import os
import json
import shutil
import subprocess
import inquirer


def ensure_aws_credentials(quiet=True):
    """Refresh SAML AWS credentials if they are stale.

    Credentials come from `awslogin`, which writes them to ~/.aws/credentials
    under both [saml] and [default]. The hypershift CLI and the AWS SDK then
    pick them up through the default credential chain, so no --aws-creds flag
    is needed anywhere.

    This is a no-op (~40ms) when the current credentials are still valid.
    Returns True if usable credentials are in place.
    """
    awslogin = shutil.which("awslogin")
    if awslogin is None:
        print(
            "Warning: 'awslogin' not found on PATH; relying on whatever AWS "
            "credentials are already configured.",
            file=sys.stderr,
        )
        return False

    cmd = [awslogin]
    if quiet:
        cmd.append("--quiet")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(
            "Error: could not obtain AWS credentials. Run 'awslogin' manually "
            "to see why (a missing Kerberos ticket is the usual cause: run 'kinit').",
            file=sys.stderr,
        )
        sys.exit(1)
    return True


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
