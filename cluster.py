import os
import subprocess
import sys
import argparse
import inquirer
import requests
import json

from utils import safe_prompt, load_input_file, merge_inputs
from config import ensure_config_exists_or_exit, load_config, run_config_interactive

CFG = None

def list_infra():
    if not os.path.exists(CFG.get("infra_dir")):
        os.makedirs(CFG.get("infra_dir"), exist_ok=True)
    return sorted([d for d in os.listdir(CFG.get("infra_dir")) if os.path.isdir(os.path.join(CFG.get("infra_dir"), d))])

def select_infra():
    infra_list = list_infra()
    if not infra_list:
        print("No infrastructures available.")
        return None
    questions = [inquirer.List("infra", message="Select an infrastructure", choices=infra_list)]
    answers = safe_prompt(questions)
    return answers["infra"]

def resolve_release_image(version, version_type):
    version = str(version)
    if version_type in ("ci", "nightly"):
        try:
            url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{version}.0-0.{version_type}/latest"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("pullSpec", f"Error: No release image found for {version} {version_type}")
        except requests.RequestException as e:
            print(f"Error fetching latest {version} {version_type} release image: {e}")
            sys.exit(1)

    try:
        url = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/tags"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        for tag in data["tags"]:
            if tag["name"].startswith(version):
                return tag["pullSpec"]
    except requests.RequestException as e:
        print(f"Error fetching stable release tags: {e}")
        sys.exit(1)

def get_release_image():
    choices = ["5.0", "4.23", "4.22", "4.21", "4.20", "4.19", "4.18", "4.17", "4.16", "4.15", "4.14"] + ["Specify release image pullspec"]

    questions = [inquirer.List("selection", message="Select a major version or enter a release image pullspec", choices=choices)]
    answers = safe_prompt(questions)

    if answers["selection"] == "Specify release image pullspec":
        questions = [inquirer.Text("pullspec", message="Enter release image pullspec")]
        pullspec_answers = safe_prompt(questions)
        return pullspec_answers["pullspec"]

    major_version = answers["selection"]
    version_choices = ["ci", "nightly", "stable"]

    questions = [inquirer.List("version_type", message=f"Select a version type for {major_version}", choices=version_choices)]
    version_answers = safe_prompt(questions)

    return resolve_release_image(major_version, version_answers["version_type"])

def select_access_mode():
    choices = ["Public", "PublicAndPrivate", "Private"]
    questions = [inquirer.List("access_mode", message="Select an access mode", choices=choices)]
    answers = safe_prompt(questions)
    return answers["access_mode"]

def select_replica_mode():
    choices = ["SingleReplica", "HighlyAvailable"]
    questions = [
        inquirer.List("control_plane", message="Select control plane mode", choices=choices),
        inquirer.List("infrastructure", message="Select infrastructure mode", choices=choices)
    ]
    answers = safe_prompt(questions)
    return answers["control_plane"], answers["infrastructure"]

def select_control_plane_version():
    choices = ["v2", "v1"]
    questions = [inquirer.List("cp_version", message="Select control plane version", choices=choices)]
    answers = safe_prompt(questions)
    return answers["cp_version"]

def get_hosted_clusters():
    try:
        result = subprocess.run(["oc", "get", "hc", "-n", "clusters", "--no-headers"], capture_output=True, text=True, check=True)
        return [line.split()[0] for line in result.stdout.splitlines() if line]
    except subprocess.CalledProcessError as e:
        print(f"Error fetching hosted clusters: {e}")
        return []

def select_hosted_cluster():
    clusters = get_hosted_clusters()
    if not clusters:
        print("No hosted clusters found.")
        return None
    questions = [inquirer.List("hc", message="Select a HostedCluster", choices=clusters)]
    answers = safe_prompt(questions)
    return answers["hc"]

def delete_hosted_cluster(params=None):
    params = dict(params) if params else {}

    if "cluster" in params:
        hc_name = params["cluster"]
    else:
        hc_name = select_hosted_cluster()

    if not hc_name:
        print("No hosted cluster selected. Exiting.")
        return

    command = f"oc delete hc -n clusters {hc_name} --wait=false"

    print(f"Executing: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
        print(f"HostedCluster {hc_name} deleted successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error deleting hosted cluster: {e}")

def create_kubeconfig(params=None):
    params = dict(params) if params else {}

    if "cluster" in params:
        hc_name = params["cluster"]
    else:
        hc_name = select_hosted_cluster()

    if not hc_name:
        print("No hosted cluster selected. Exiting.")
        return

    if "kubeconfig_name" in params:
        kubeconfig_name = params["kubeconfig_name"]
    else:
        questions = [inquirer.Text("kubeconfig_name", message="Enter the kubeconfig name")]
        answers = safe_prompt(questions)
        kubeconfig_name = answers["kubeconfig_name"]

    kubeconfig_dir = CFG.get("kubeconfig_dir")
    if not os.path.isdir(kubeconfig_dir):
        os.makedirs(kubeconfig_dir, exist_ok=True)
    kubeconfig_path = os.path.join(kubeconfig_dir, f"{kubeconfig_name}.kubeconfig")
    command = f"{CFG.get('hypershift_path', 'hypershift')} create kubeconfig --name {hc_name} > {kubeconfig_path}"

    print(f"Generating kubeconfig: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
        print(f"Kubeconfig created at {kubeconfig_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error creating kubeconfig: {e}")

def _is_hypershift_repo(directory):
    try:
        result = subprocess.run(
            ["git", "-C", directory, "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True)
        return "hypershift" in result.stdout.strip().lower()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def _resolve_hypershift_repo_dir():
    cwd = os.getcwd()
    if _is_hypershift_repo(cwd):
        return cwd
    configured = CFG.get("hypershift_repo_dir")
    if configured and os.path.isdir(configured):
        return configured
    return None

def render_cluster_yaml(infra, release_image, access_mode, control_plane, infrastructure, cp_version, local_cpo, node_count, instance_type):
    infra_path = os.path.join(CFG.get("infra_dir"), infra)
    yaml_path = os.path.join(infra_path, "cluster.yaml")

    hypershift_cmd = CFG.get("hypershift_path", "hypershift")

    infra_out = os.path.join(infra_path, "infra.json")
    iam_out = os.path.join(infra_path, "iam.json")

    if local_cpo:
        repo_dir = _resolve_hypershift_repo_dir()
        image_prefix = CFG.get("local_cpo_image_prefix")
        if repo_dir and image_prefix:
            try:
                result = subprocess.run([
                    "git", "-C", repo_dir, "rev-parse", "--short", "HEAD"
                ], capture_output=True, text=True, check=True)
                short_hash = result.stdout.strip()
                if short_hash:
                    cpo_image_flag = f"--control-plane-operator-image {image_prefix}:{short_hash}"
                else:
                    cpo_image_flag = ""
            except subprocess.CalledProcessError as e:
                print(f"Warning: Failed to compute local CPO image from repo {repo_dir}: {e}")
                cpo_image_flag = ""
        else:
            cpo_image_flag = ""
    else:
        cpo_image_flag = ""

    custom_domain_flag = ""
    if access_mode == "Private" or access_mode == "PublicAndPrivate":
        if CFG.get("external_dns_domain"):
            custom_domain_flag = f"--external-dns-domain {CFG.get('external_dns_domain')}"
        else:
            custom_domain_flag = ""

    if cp_version == "v2":
        cp_version_flag = "--annotations hypershift.openshift.io/cpo-v2=true"
    else:
        cp_version_flag = ""

    if os.path.exists(infra_out):
        with open(infra_out, "r") as file:
            data = json.load(file)
    else:
        print("cannot open infra.json in infrastructure directory")
        return

    command = f"{hypershift_cmd} create cluster aws --render \
--aws-creds {CFG.get('aws_creds_path')} \
--instance-type {instance_type} \
--region {data.get('region')} \
--control-plane-availability-policy {control_plane} \
--infra-availability-policy {infrastructure} \
--auto-repair \
--generate-ssh \
--name {data.get('Name')} \
--endpoint-access {access_mode} \
--node-pool-replicas {node_count} \
--pull-secret {CFG.get('pull_secret_path')} \
--infra-id {data.get('infraID')} \
--infra-json {infra_out} \
--iam-json {iam_out} \
--base-domain {data.get('baseDomain')} \
{custom_domain_flag} \
--release-image {release_image} \
{cpo_image_flag} \
--annotations hypershift.openshift.io/cleanup-cloud-resources=true \
{cp_version_flag} \
--render-sensitive \
--render > {yaml_path}"

    print(f"Executing: {command}")
    subprocess.run(command, shell=True, check=True)
    print(f"Cluster YAML written to {yaml_path}")

def list_yaml_infras():
    if not os.path.exists(CFG.get("infra_dir")):
        return []
    return [d for d in os.listdir(CFG.get("infra_dir")) if os.path.isfile(os.path.join(CFG.get("infra_dir"), d, "cluster.yaml"))]

def select_yaml_infra():
    infra_list = list_yaml_infras()
    if not infra_list:
        print("No infrastructures with cluster.yaml found.")
        return None
    questions = [inquirer.List("infra", message="Select an infrastructure to apply", choices=infra_list)]
    answers = safe_prompt(questions)
    return answers["infra"]

def apply_cluster_yaml(params=None):
    params = dict(params) if params else {}

    if "infra" in params:
        infra = params["infra"]
    else:
        infra = select_yaml_infra()

    if not infra:
        print("No valid infrastructure selected. Exiting.")
        return

    yaml_path = os.path.join(CFG.get("infra_dir"), infra, "cluster.yaml")

    if not os.path.exists(yaml_path):
        print(f"Error: cluster.yaml not found in {infra}.")
        return

    command = f"oc apply -f {yaml_path}"
    print(f"Applying {yaml_path} to the Kubernetes cluster...")

    try:
        subprocess.run(command, shell=True, check=True)
        print("Cluster applied successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error applying cluster: {e}")

def _render_command(params):
    # 1. Select infra
    if "infra" in params:
        infra = params["infra"]
    else:
        infra = select_infra()
    if not infra:
        print("No infrastructure selected. Exiting.")
        return

    # 2. Resolve release image
    if "release_image" in params:
        release_image = params["release_image"]
    elif "version" in params:
        version = str(params["version"])
        if "version_type" in params:
            version_type = params["version_type"]
        else:
            version_choices = ["ci", "nightly", "stable"]
            questions = [inquirer.List("version_type", message=f"Select a version type for {version}", choices=version_choices)]
            answers = safe_prompt(questions)
            version_type = answers["version_type"]
        release_image = resolve_release_image(version, version_type)
    else:
        release_image = get_release_image()

    # 3. Access mode
    if "access_mode" in params:
        access_mode = params["access_mode"]
    else:
        access_mode = select_access_mode()

    # 4. Replica modes
    control_plane = params.get("control_plane_mode")
    infrastructure = params.get("infrastructure_mode")

    if control_plane is None and infrastructure is None:
        control_plane, infrastructure = select_replica_mode()
    elif control_plane is None:
        choices = ["SingleReplica", "HighlyAvailable"]
        questions = [inquirer.List("control_plane", message="Select control plane mode", choices=choices)]
        answers = safe_prompt(questions)
        control_plane = answers["control_plane"]
    elif infrastructure is None:
        choices = ["SingleReplica", "HighlyAvailable"]
        questions = [inquirer.List("infrastructure", message="Select infrastructure mode", choices=choices)]
        answers = safe_prompt(questions)
        infrastructure = answers["infrastructure"]

    # 5. Control plane version
    if "cp_version" in params:
        cp_version = params["cp_version"]
    else:
        cp_version = select_control_plane_version()

    # 6. Local CPO
    if "local_cpo" in params:
        local_cpo = params["local_cpo"]
    else:
        questions = [inquirer.Confirm("local_cpo", message="Use local control plane operator?", default=False)]
        answers = safe_prompt(questions)
        local_cpo = answers["local_cpo"]

    # 7. Node count and instance type
    node_questions = []
    if "node_count" not in params:
        node_questions.append(inquirer.Text("node_count", message="Enter number of nodes", default="2"))
    if "instance_type" not in params:
        node_questions.append(inquirer.Text("instance_type", message="Enter instance type", default="m6i.xlarge"))
    if node_questions:
        answers = safe_prompt(node_questions)
        params.update(answers)

    node_count = params.get("node_count", "2")
    instance_type = params.get("instance_type", "m6i.xlarge")

    render_cluster_yaml(infra, release_image, access_mode, control_plane, infrastructure, cp_version, local_cpo, node_count, instance_type)

def _parse_args():
    parser = argparse.ArgumentParser(description="Manage HyperShift HostedClusters")
    subparsers = parser.add_subparsers(dest="command")

    render_p = subparsers.add_parser("render", help="Render cluster.yaml for a HostedCluster")
    render_p.add_argument("-i", "--input", dest="input_file", help="Input YAML/JSON file with parameters")
    render_p.add_argument("--infra", help="Infrastructure name")
    render_p.add_argument("--release-image", dest="release_image", help="Release image pullspec")
    render_p.add_argument("--version", help="OCP major version (e.g. 4.18)")
    render_p.add_argument("--version-type", dest="version_type", choices=["ci", "nightly", "stable"],
                          help="Version stream (used with --version)")
    render_p.add_argument("--access-mode", dest="access_mode",
                          choices=["Public", "PublicAndPrivate", "Private"],
                          help="Endpoint access mode")
    render_p.add_argument("--control-plane-mode", dest="control_plane_mode",
                          choices=["SingleReplica", "HighlyAvailable"],
                          help="Control plane availability mode")
    render_p.add_argument("--infrastructure-mode", dest="infrastructure_mode",
                          choices=["SingleReplica", "HighlyAvailable"],
                          help="Infrastructure availability mode")
    render_p.add_argument("--cp-version", dest="cp_version", choices=["v1", "v2"],
                          help="Control plane version")
    render_p.add_argument("--local-cpo", dest="local_cpo", action="store_true", default=None,
                          help="Use local control plane operator")
    render_p.add_argument("--no-local-cpo", dest="local_cpo", action="store_false",
                          help="Do not use local control plane operator")
    render_p.add_argument("--node-count", dest="node_count", help="Number of worker nodes")
    render_p.add_argument("--instance-type", dest="instance_type", help="EC2 instance type")

    apply_p = subparsers.add_parser("apply", help="Apply a rendered cluster.yaml")
    apply_p.add_argument("-i", "--input", dest="input_file", help="Input YAML/JSON file")
    apply_p.add_argument("--infra", help="Infrastructure name")

    k_p = subparsers.add_parser("k", help="Generate kubeconfig for a HostedCluster")
    k_p.add_argument("-i", "--input", dest="input_file", help="Input YAML/JSON file")
    k_p.add_argument("--cluster", help="HostedCluster name")
    k_p.add_argument("--kubeconfig-name", dest="kubeconfig_name", help="Output kubeconfig file name")

    rm_p = subparsers.add_parser("rm", help="Delete a HostedCluster")
    rm_p.add_argument("-i", "--input", dest="input_file", help="Input YAML/JSON file")
    rm_p.add_argument("--cluster", help="HostedCluster name")

    subparsers.add_parser("list", help="List HostedClusters")
    subparsers.add_parser("config", help="Configure settings interactively")

    return parser.parse_args()

def main():
    if len(sys.argv) < 2:
        questions = [inquirer.List("command", message="Select a command", choices=["render", "apply", "k", "rm", "list", "config"])]
        answers = safe_prompt(questions)
        command = answers["command"]
        params = {}
    else:
        args = _parse_args()
        command = args.command
        input_data = load_input_file(args.input_file) if getattr(args, "input_file", None) else {}
        params = merge_inputs(args, input_data)

    if command == "config":
        run_config_interactive()
        return

    ensure_config_exists_or_exit("cluster.py")
    global CFG
    CFG = load_config()

    if command == "render":
        _render_command(params)
    elif command == "apply":
        apply_cluster_yaml(params)
    elif command == "k":
        create_kubeconfig(params)
    elif command == "rm":
        delete_hosted_cluster(params)
    elif command == "list":
        clusters = get_hosted_clusters()
        if clusters:
            print("Hosted Clusters:")
            for cluster in clusters:
                print(f"- {cluster}")
        else:
            print("No hosted clusters found.")
    else:
        print("Invalid command. Use 'render', 'apply', 'k', 'rm', 'list', or 'config'.")

if __name__ == "__main__":
    main()
