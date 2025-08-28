import os
import json
import pathlib
import platform
import subprocess
import sys

import inquirer

from utils import safe_prompt


GENERIC_DEFAULTS = {
    "name": "",
    "region": "",
    "base_domain": "",
    "hypershift_path": "hypershift",
    "infra_dir": "",
    "aws_creds_path": "",
    "pull_secret_path": "",
    "kubeconfig_dir": "",
    "oidc_s3_bucket_name": "",
    "oidc_s3_region": "",
    "external_dns_domain": "",
    "hypershift_repo_dir": "",
    "local_cpo_image_prefix": "",
}


def _config_path():
    """Returns the path Infra's configuration file"""
    return os.path.join(_os_config_dir(), "config.json")


def _os_config_dir() -> str:
    """Get the configuration directory where to load the configuration from"""

    # First check if the legacy conf dir is in use
    legacy_config_dir = os.path.join(pathlib.Path.home(), ".infra")
    if os.path.exists(legacy_config_dir):
        return legacy_config_dir

    platform_sys = platform.system()
    user_config_dir = None
    match platform_sys:
        case "Linux":
            user_config_dir = os.getenv("XDG_CONFIG_HOME")
            if user_config_dir is None:
                print(
                    "XDG_CONFIG_HOME is not defined, trying systemd defaults...",
                    file=sys.stderr,
                )

                import shutil

                systemd_path_location = shutil.which("systemd-path")
                if systemd_path_location is None:
                    print(
                        "systemd-path tool not found, falling back to legacy path ~/.infra",
                        file=sys.stderr,
                    )

                    user_config_dir = legacy_config_dir
                else:
                    user_config_dir = os.path.join(
                        subprocess.check_output(
                            [systemd_path_location, "user-configuration"], text=True
                        ).strip(),
                        "infra",
                    )

        case "Darwin":
            user_config_dir = os.path.join(
                pathlib.Path.home(), "Library", "Application Support", "Infra"
            )
        case "Windows":
            appdata_location = os.getenv("AppData")
            if appdata_location is None:
                print(
                    "AppData is not defined, aborting...",
                    file=sys.stderr,
                )
                sys.exit(1)

            user_config_dir = os.path.join(appdata_location, "infra")
        case _:
            print(f"Unrecognized operating system {platform_sys}", file=sys.stderr)
    if user_config_dir is None:
        print(
            "Unable to automatically determine the right config file location",
            file=sys.stderr,
        )
        sys.exit(1)
    return user_config_dir


def expand_path(path_value):
    if not isinstance(path_value, str):
        return path_value
    return os.path.expanduser(os.path.expandvars(path_value))


def load_config():
    config_path = _config_path()
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
            return cfg
    except FileNotFoundError:
        raise
    except json.JSONDecodeError:
        print(
            f"Config file is corrupted or invalid JSON: {config_path}", file=sys.stderr
        )
        print("Please run the 'config' subcommand to repair it.", file=sys.stderr)
        sys.exit(1)


def save_config(cfg):
    config_dir = _os_config_dir()
    if not os.path.isdir(config_dir):
        os.makedirs(config_dir, exist_ok=True)
    config_path = _config_path()
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)
        print(f"Configuration written to: {config_path}", file=sys.stderr)


def ensure_config_exists_or_exit(invocation_hint):
    config_path = _config_path()
    if not os.path.isfile(config_path):
        print(f"Configuration not found at: {config_path}", file=sys.stderr)
        print(f"Run: {invocation_hint} config", file=sys.stderr)
        sys.exit(1)


def prompt_and_write_config(existing_cfg=None):
    cfg = (existing_cfg or {}).copy()

    def get_default(key):
        return (
            cfg.get(key)
            if cfg.get(key) not in (None, "")
            else GENERIC_DEFAULTS.get(key, "")
        )

    questions = [
        inquirer.Text("name", message="Default name", default=get_default("name")),
        inquirer.Text(
            "region", message="Default region", default=get_default("region")
        ),
        inquirer.Text(
            "base_domain",
            message="Default base domain",
            default=get_default("base_domain"),
        ),
        inquirer.Text(
            "hypershift_path",
            message="Path to hypershift binary (or 'hypershift' if on PATH)",
            default=get_default("hypershift_path"),
        ),
        inquirer.Text(
            "infra_dir",
            message="Directory to store infrastructures",
            default=get_default("infra_dir"),
        ),
        inquirer.Text(
            "aws_creds_path",
            message="Path to AWS credentials file",
            default=get_default("aws_creds_path"),
        ),
        inquirer.Text(
            "pull_secret_path",
            message="Path to pull-secret file",
            default=get_default("pull_secret_path"),
        ),
        inquirer.Text(
            "kubeconfig_dir",
            message="Directory to store kubeconfigs",
            default=get_default("kubeconfig_dir"),
        ),
        inquirer.Text(
            "oidc_s3_bucket_name",
            message="OIDC S3 bucket name (for IAM create)",
            default=get_default("oidc_s3_bucket_name"),
        ),
        inquirer.Text(
            "oidc_s3_region",
            message="OIDC S3 region (for IAM create)",
            default=get_default("oidc_s3_region"),
        ),
        inquirer.Text(
            "external_dns_domain",
            message="External DNS domain (optional)",
            default=get_default("external_dns_domain"),
        ),
        inquirer.Text(
            "hypershift_repo_dir",
            message="Path to local hypershift repo (optional)",
            default=get_default("hypershift_repo_dir"),
        ),
        inquirer.Text(
            "local_cpo_image_prefix",
            message="Local CPO image prefix (e.g. quay.io/you/hypershift) (optional)",
            default=get_default("local_cpo_image_prefix"),
        ),
    ]

    answers = safe_prompt(questions)

    # Normalize and expand path-like values
    answers["infra_dir"] = expand_path(answers.get("infra_dir"))
    answers["aws_creds_path"] = expand_path(answers.get("aws_creds_path"))
    answers["pull_secret_path"] = expand_path(answers.get("pull_secret_path"))
    answers["kubeconfig_dir"] = expand_path(answers.get("kubeconfig_dir"))
    answers["hypershift_path"] = expand_path(answers.get("hypershift_path"))
    answers["hypershift_repo_dir"] = expand_path(answers.get("hypershift_repo_dir"))

    # Ensure directories exist
    if answers.get("infra_dir"):
        os.makedirs(answers["infra_dir"], exist_ok=True)
    if answers.get("kubeconfig_dir"):
        os.makedirs(answers["kubeconfig_dir"], exist_ok=True)

    save_config(answers)

    return answers


def run_config_interactive():
    try:
        existing = load_config()
    except FileNotFoundError:
        existing = None
    prompt_and_write_config(existing_cfg=existing)
