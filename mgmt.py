import os
import sys
import subprocess
import argparse
import inquirer
import requests

from utils import safe_prompt, load_input_file, merge_inputs
from config import ensure_config_exists_or_exit, load_config, run_config_interactive, expand_path

CFG = None


def execute_command(command, env=None):
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=run_env)
    for line in process.stdout:
        print(line, end="")
    process.wait()
    return process.returncode


def _get_latest_stable_release():
    try:
        url = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/latest"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("pullSpec")
    except requests.RequestException as e:
        print(f"Error fetching latest stable release: {e}")
        return None


# -- HyperShift Operator Install -----------------------------------------------


def _resolve_hypershift_binary():
    cwd = os.getcwd()
    local_bin = os.path.join(cwd, "bin", "hypershift")
    if os.path.isfile(local_bin) and os.access(local_bin, os.X_OK):
        return local_bin
    return CFG.get("hypershift_path", "hypershift")


def _resolve_hypershift_image(hypershift_bin, explicit_image=None):
    if explicit_image:
        return explicit_image
    image_prefix = CFG.get("local_cpo_image_prefix", "quay.io/csrwng/hypershift")
    repo_dir = None
    cwd = os.getcwd()
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True)
        if "hypershift" in result.stdout.strip().lower():
            repo_dir = cwd
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    if not repo_dir:
        repo_dir = CFG.get("hypershift_repo_dir", "")
    if repo_dir:
        try:
            result = subprocess.run(
                ["git", "-C", repo_dir, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=True)
            short_hash = result.stdout.strip()
            if short_hash:
                return f"{image_prefix}:{short_hash}"
        except subprocess.CalledProcessError:
            pass
    try:
        result = subprocess.run(
            [hypershift_bin, "version", "--commit-only"],
            capture_output=True, text=True, check=True)
        commit = result.stdout.strip()
        if commit:
            return f"{image_prefix}:{commit[:7]}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None


def install_ho(params=None):
    params = dict(params) if params else {}

    hypershift_bin = _resolve_hypershift_binary()
    hypershift_image = _resolve_hypershift_image(hypershift_bin, params.get("hypershift_image"))

    if not params.get("skip_check", False) and hypershift_image:
        tag = hypershift_image.rsplit(":", 1)[-1] if ":" in hypershift_image else ""
        if tag:
            try:
                result = subprocess.run(
                    [hypershift_bin, "version", "--commit-only"],
                    capture_output=True, text=True, check=True)
                current_commit = result.stdout.strip()
                if not current_commit.startswith(tag):
                    print(f"Attempting to install commit {tag} with binary {current_commit[:len(tag)]}. Compile before installing.")
                    return
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    pull_secret = CFG.get("pull_secret_path", "")
    aws_creds = CFG.get("aws_creds_path", "")
    region = CFG.get("region", "us-east-2")
    oidc_bucket = CFG.get("oidc_s3_bucket_name", "")
    oidc_region = CFG.get("oidc_s3_region", region)
    external_dns_domain = CFG.get("external_dns_domain", "")

    command = (
        f"{hypershift_bin} install"
        f" --oidc-storage-provider-s3-bucket-name {oidc_bucket}"
        f" --oidc-storage-provider-s3-credentials {aws_creds}"
        f" --oidc-storage-provider-s3-region {oidc_region}"
        f" --private-platform AWS"
        f" --aws-private-creds {aws_creds}"
        f" --aws-private-region {region}"
        f" --metrics-set All"
        f" --development"
        f" --platform-monitoring OperatorOnly"
        f" --enable-uwm-telemetry-remote-write"
        f" --monitoring-dashboards"
        f" --enable-cpo-overrides"
        f" --enable-ci-debug-output"
    )

    if external_dns_domain:
        command += f" --external-dns-provider=aws"
        command += f" --external-dns-credentials={aws_creds}"
        command += f" --external-dns-domain-filter={external_dns_domain}"
    if hypershift_image:
        command += f" --hypershift-image {hypershift_image}"

    print(f"\nInstalling HyperShift operator...\n{command}")
    if execute_command(command) != 0:
        print("Failed to install HyperShift operator.")
        return

    execute_command("oc scale deployment/operator -n hypershift --replicas=1")

    print("\nWaiting for HyperShift operator rollout...")
    if execute_command("oc rollout status deployment/operator -n hypershift") == 0:
        print("HyperShift operator installed successfully.")
    else:
        print("HyperShift operator rollout did not complete.")


# -- Dev HostedCluster on CI Management Cluster --------------------------------


def create_dev(params=None):
    params = dict(params) if params else {}

    ci_kubeconfig = expand_path(CFG.get("ci_kubeconfig", ""))
    ci_namespace = CFG.get("ci_namespace", "cewong")
    if not ci_kubeconfig or not os.path.exists(ci_kubeconfig):
        print(f"Error: CI kubeconfig not found at: {ci_kubeconfig}")
        print("Configure ci_kubeconfig in 'mgmt config'.")
        return

    name = params.get("name", os.environ.get("NAME", f"{ci_namespace}-dev"))
    release_image = params.get("release_image", os.environ.get("RELEASE_IMAGE"))
    if not release_image:
        print("Fetching latest stable release image...")
        release_image = _get_latest_stable_release()
        if not release_image:
            print("Error: Could not determine release image. Set RELEASE_IMAGE env var.")
            return
    print(f"Release image: {release_image}")

    hypershift_cmd = _resolve_hypershift_binary()
    aws_creds = CFG.get("aws_creds_path", "")
    region = CFG.get("region", "us-east-2")
    base_domain = CFG.get("base_domain", "")
    pull_secret = CFG.get("pull_secret_path", "")
    instance_type = params.get("instance_type", "m6i.xlarge")
    node_pool_replicas = params.get("node_pool_replicas", "1")
    zones = params.get("zones", f"{region}a,{region}b,{region}c")

    env = {"KUBECONFIG": ci_kubeconfig}

    command = (
        f"{hypershift_cmd} create cluster aws"
        f" --aws-creds {aws_creds}"
        f" --instance-type {instance_type}"
        f" --region {region}"
        f" --auto-repair"
        f" --generate-ssh"
        f" --name {name}"
        f" --namespace {ci_namespace}"
        f" --node-pool-replicas {node_pool_replicas}"
        f" --pull-secret {pull_secret}"
        f" --base-domain {base_domain}"
        f" --release-image {release_image}"
        f" --zones {zones}"
        f" --node-selector=hypershift.openshift.io/control-plane=true"
        f" --cluster-cidr 10.136.0.0/14"
        f" --service-cidr 172.28.0.0/16"
        f" --public-only"
    )

    print(f"\nCreating dev HostedCluster...\n{command}")
    if execute_command(command, env=env) == 0:
        print(f"\nDev HostedCluster '{name}' created on CI management cluster.")
    else:
        print("Failed to create dev HostedCluster.")


def destroy_dev(params=None):
    params = dict(params) if params else {}

    ci_kubeconfig = expand_path(CFG.get("ci_kubeconfig", ""))
    ci_namespace = CFG.get("ci_namespace", "cewong")
    aws_creds = CFG.get("aws_creds_path", "")

    name = params.get("name", os.environ.get("NAME", f"{ci_namespace}-dev"))

    env = {"KUBECONFIG": ci_kubeconfig}

    command = (
        f"{_resolve_hypershift_binary()} destroy cluster aws"
        f" --aws-creds {aws_creds}"
        f" --name {name}"
        f" --namespace {ci_namespace}"
    )

    print(f"Destroying dev HostedCluster '{name}'...\n{command}")
    if execute_command(command, env=env) == 0:
        print(f"Dev HostedCluster '{name}' destroyed.")
    else:
        print("Failed to destroy dev HostedCluster.")


def devkubeconfig(params=None):
    params = dict(params) if params else {}

    ci_kubeconfig = expand_path(CFG.get("ci_kubeconfig", ""))
    ci_namespace = CFG.get("ci_namespace", "cewong")

    name = params.get("name", os.environ.get("NAME", f"{ci_namespace}-dev"))

    env = {"KUBECONFIG": ci_kubeconfig}

    result = subprocess.run(
        f"oc get hc/{name} -n {ci_namespace} -o jsonpath='{{ .status.kubeconfig.name }}'",
        shell=True, capture_output=True, text=True, env={**os.environ, **env})
    secret_name = result.stdout.strip()
    if not secret_name:
        print("Kubeconfig does not exist yet.")
        return

    kubeconfig_dir = CFG.get("kubeconfig_dir", expand_path("~/data/kubeconfig"))
    os.makedirs(kubeconfig_dir, exist_ok=True)
    kubeconfig_path = os.path.join(kubeconfig_dir, "dev.kubeconfig")

    command = f"oc get secret -n {ci_namespace} {secret_name} -o jsonpath='{{ .data.kubeconfig }}' | base64 -d > {kubeconfig_path}"

    print(f"Extracting kubeconfig for '{name}'...")
    if execute_command(command, env=env) == 0:
        print(f"Kubeconfig written to: {kubeconfig_path}")
        print(f"  export KUBECONFIG={kubeconfig_path}")
    else:
        print("Failed to extract kubeconfig.")


# -- CLI -----------------------------------------------------------------------


def _parse_args():
    parser = argparse.ArgumentParser(description="Manage AWS management clusters and dev HostedClusters")
    subparsers = parser.add_subparsers(dest="command")

    ho_install = subparsers.add_parser("install-ho", help="Install HyperShift operator on a management cluster")
    ho_install.add_argument("--hypershift-image", dest="hypershift_image", help="HyperShift operator image override")
    ho_install.add_argument("--skip-check", dest="skip_check", action="store_true", default=False,
                            help="Skip binary/image commit match check")

    dev_create = subparsers.add_parser("create-dev", help="Create a dev HostedCluster on CI management cluster")
    dev_create.add_argument("--name", help="HostedCluster name")
    dev_create.add_argument("--release-image", dest="release_image", help="Release image pullspec")
    dev_create.add_argument("--instance-type", dest="instance_type", help="EC2 instance type")
    dev_create.add_argument("--node-pool-replicas", dest="node_pool_replicas", help="Node pool replica count")
    dev_create.add_argument("--zones", help="Availability zones (comma-separated)")

    dev_destroy = subparsers.add_parser("destroy-dev", help="Destroy dev HostedCluster")
    dev_destroy.add_argument("--name", help="HostedCluster name")

    dev_k = subparsers.add_parser("devkubeconfig", help="Extract dev HostedCluster kubeconfig")
    dev_k.add_argument("--name", help="HostedCluster name")

    subparsers.add_parser("config", help="Configure settings interactively")

    return parser.parse_args()


def main():
    if len(sys.argv) < 2:
        questions = [
            inquirer.List("command", message="Select a command",
                          choices=["install-ho", "create-dev", "destroy-dev", "devkubeconfig", "config"])
        ]
        answers = safe_prompt(questions)
        command = answers["command"]
        params = {}
    else:
        args = _parse_args()
        command = args.command
        params = merge_inputs(args, {})

    if command == "config":
        run_config_interactive()
        return

    ensure_config_exists_or_exit("mgmt")
    global CFG
    CFG = load_config()

    if command == "install-ho":
        install_ho(params)
    elif command == "create-dev":
        create_dev(params)
    elif command == "destroy-dev":
        destroy_dev(params)
    elif command == "devkubeconfig":
        devkubeconfig(params)
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
