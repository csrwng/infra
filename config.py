import os
import json
import sys
import inquirer

from utils import safe_prompt


CONFIG_DIR = os.path.expanduser("~/.infra")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


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


def expand_path(path_value):
    if not isinstance(path_value, str):
        return path_value
    return os.path.expanduser(os.path.expandvars(path_value))


def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
            return cfg
    except FileNotFoundError:
        raise
    except json.JSONDecodeError:
        print("Config file is corrupted or invalid JSON:", CONFIG_PATH)
        print("Please run the 'config' subcommand to repair it.")
        sys.exit(1)


def save_config(cfg):
    if not os.path.isdir(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def ensure_config_exists_or_exit(invocation_hint):
    if not os.path.isfile(CONFIG_PATH):
        print("Configuration not found at:", CONFIG_PATH)
        print(f"Run: {invocation_hint} config")
        sys.exit(1)


def prompt_and_write_config(existing_cfg=None):
    cfg = (existing_cfg or {}).copy()

    def get_default(key):
        return cfg.get(key) if cfg.get(key) not in (None, "") else GENERIC_DEFAULTS.get(key, "")

    questions = [
        inquirer.Text("name", message="Default name", default=get_default("name")),
        inquirer.Text("region", message="Default region", default=get_default("region")),
        inquirer.Text("base_domain", message="Default base domain", default=get_default("base_domain")),
        inquirer.Text("hypershift_path", message="Path to hypershift binary (or 'hypershift' if on PATH)", default=get_default("hypershift_path")),
        inquirer.Text("infra_dir", message="Directory to store infrastructures", default=get_default("infra_dir")),
        inquirer.Text("aws_creds_path", message="Path to AWS credentials file", default=get_default("aws_creds_path")),
        inquirer.Text("pull_secret_path", message="Path to pull-secret file", default=get_default("pull_secret_path")),
        inquirer.Text("kubeconfig_dir", message="Directory to store kubeconfigs", default=get_default("kubeconfig_dir")),
        inquirer.Text("oidc_s3_bucket_name", message="OIDC S3 bucket name (for IAM create)", default=get_default("oidc_s3_bucket_name")),
        inquirer.Text("oidc_s3_region", message="OIDC S3 region (for IAM create)", default=get_default("oidc_s3_region")),
        inquirer.Text("external_dns_domain", message="External DNS domain (optional)", default=get_default("external_dns_domain")),
        inquirer.Text("hypershift_repo_dir", message="Path to local hypershift repo (optional)", default=get_default("hypershift_repo_dir")),
        inquirer.Text("local_cpo_image_prefix", message="Local CPO image prefix (e.g. quay.io/you/hypershift) (optional)", default=get_default("local_cpo_image_prefix")),
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
    print("Configuration written to:", CONFIG_PATH)

    return answers


def run_config_interactive():
    try:
        existing = load_config()
    except FileNotFoundError:
        existing = None
    prompt_and_write_config(existing_cfg=existing)


