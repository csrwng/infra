import os
import subprocess
import sys
import inquirer
import requests
import json

from utils import safe_prompt
from config import ensure_config_exists_or_exit, load_config, run_config_interactive

CFG = None

def list_infra():
    """Lists available infrastructure directories."""
    if not os.path.exists(CFG.get("infra_dir")):
        os.makedirs(CFG.get("infra_dir"), exist_ok=True)
    
    return sorted([d for d in os.listdir(CFG.get("infra_dir")) if os.path.isdir(os.path.join(CFG.get("infra_dir"), d))])

def select_infra():
    """Prompts user to select an infrastructure."""
    infra_list = list_infra()
    
    if not infra_list:
        print("No infrastructures available.")
        return None

    questions = [inquirer.List("infra", message="Select an infrastructure", choices=infra_list)]
    answers = safe_prompt(questions)
    
    return answers["infra"]

def get_release_image():
    """Prompts user for a major version or a specific release image pullspec."""
    choices =  ["4.20", "4.19", "4.18", "4.17", "4.16", "4.15", "4.14"] + ["Specify release image pullspec"]
    
    questions = [inquirer.List("selection", message="Select a major version or enter a release image pullspec", choices=choices)]
    answers = safe_prompt(questions)
    
    if answers["selection"] == "Specify release image pullspec":
        # Prompt for a custom release image pullspec
        questions = [inquirer.Text("pullspec", message="Enter release image pullspec")]
        pullspec_answers = safe_prompt(questions)
        return pullspec_answers["pullspec"]
    
    # If a major version is selected, prompt for version type
    major_version = answers["selection"]
    version_choices = ["ci", "nightly", "stable"]
    
    questions = [inquirer.List("version_type", message=f"Select a version type for {major_version}", choices=version_choices)]
    version_answers = safe_prompt(questions)
    
    version_type = version_answers["version_type"]

    if version_type == "ci" or version_type == "nightly":
        try:
            url = f"https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/{major_version}.0-0.{version_type}/latest"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("pullSpec", f"Error: No release image found for {major_version} {version_type}")
        except requests.RequestException as e:
            print(f"Error fetching latest {major_version} {version_type} release image: {e}")
            sys.exit(1)
    
    # Fetch the release image from the API
    try:
        url = "https://amd64.ocp.releases.ci.openshift.org/api/v1/releasestream/4-stable/tags"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        for tag in data["tags"]:
            if tag["name"].startswith(major_version):
                return tag["pullSpec"]
    except requests.RequestException as e:
        print(f"Error fetching stable release tags: {e}")
        sys.exit(1)

def select_access_mode():
    """Prompts user to select an access mode."""
    choices = ["Public", "PublicAndPrivate", "Private"]
    
    questions = [inquirer.List("access_mode", message="Select an access mode", choices=choices)]
    answers = safe_prompt(questions)
    
    return answers["access_mode"]

def select_replica_mode():
    """Prompts user to select control plane and infrastructure replica modes."""
    choices = ["SingleReplica", "HighlyAvailable"]

    questions = [
        inquirer.List("control_plane", message="Select control plane mode", choices=choices),
        inquirer.List("infrastructure", message="Select infrastructure mode", choices=choices)
    ]
    
    answers = safe_prompt(questions)
    
    return answers["control_plane"], answers["infrastructure"]

def select_control_plane_version():
    """Prompts user to select control plane version."""
    choices = ["v2", "v1"]
    
    questions = [inquirer.List("cp_version", message="Select control plane version", choices=choices)]
    answers = safe_prompt(questions)
    
    return answers["cp_version"]

def get_hosted_clusters():
    """Fetches and returns a list of hosted clusters."""
    try:
        result = subprocess.run(["oc", "get", "hc", "-n", "clusters", "--no-headers"], capture_output=True, text=True, check=True)
        return [line.split()[0] for line in result.stdout.splitlines() if line]
    except subprocess.CalledProcessError as e:
        print(f"Error fetching hosted clusters: {e}")
        return []

def select_hosted_cluster():
    """Prompts user to select a hosted cluster."""
    clusters = get_hosted_clusters()
    
    if not clusters:
        print("No hosted clusters found.")
        return None

    questions = [inquirer.List("hc", message="Select a HostedCluster", choices=clusters)]
    answers = safe_prompt(questions)

    return answers["hc"]

def delete_hosted_cluster():
    """Prompts user for a hosted cluster and deletes it."""
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

def create_kubeconfig():
    """Prompts user for a hosted cluster and kubeconfig name, then generates the kubeconfig."""
    hc_name = select_hosted_cluster()
    if not hc_name:
        print("No hosted cluster selected. Exiting.")
        return

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

def render_cluster_yaml(infra, release_image, access_mode, control_plane, infrastructure, cp_version, local_cpo, node_count, instance_type):
    """Executes an external program to render the cluster YAML."""
    infra_path = os.path.join(CFG.get("infra_dir"), infra)
    yaml_path = os.path.join(infra_path, "cluster.yaml")

    hypershift_cmd = CFG.get("hypershift_path", "hypershift")

    infra_out = os.path.join(infra_path, "infra.json")
    iam_out = os.path.join(infra_path, "iam.json")

    if local_cpo:
        repo_dir = CFG.get("hypershift_repo_dir")
        image_prefix = CFG.get("local_cpo_image_prefix")
        if repo_dir and image_prefix and os.path.isdir(repo_dir):
            try:
                result = subprocess.run([
                    "git", "-C", repo_dir, "rev-parse", "--short=9", "HEAD"
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
            data = json.load(file)  # Parse JSON into a dictionary
    else:
        print("cannot open infra.json in infrastructure directory")
        return

    # Mock command (replace this with actual rendering command)
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
    """Lists infrastructures that contain a cluster.yaml file."""
    if not os.path.exists(CFG.get("infra_dir")):
        return []
    
    return [d for d in os.listdir(CFG.get("infra_dir")) if os.path.isfile(os.path.join(CFG.get("infra_dir"), d, "cluster.yaml"))]

def select_yaml_infra():
    """Prompts user to select an infrastructure that has a cluster.yaml file."""
    infra_list = list_yaml_infras()
    
    if not infra_list:
        print("No infrastructures with cluster.yaml found.")
        return None

    questions = [inquirer.List("infra", message="Select an infrastructure to apply", choices=infra_list)]
    answers = safe_prompt(questions)
    
    return answers["infra"]

def apply_cluster_yaml():
    """Applies the selected cluster.yaml to the Kubernetes cluster."""
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

def main():
    """Main function to handle command selection interactively if no argument is provided."""
    if len(sys.argv) < 2:
        # No command provided, ask the user to select one
        questions = [inquirer.List("command", message="Select a command", choices=["render", "apply", "k", "rm", "list", "config"])]
        answers = safe_prompt(questions)
        command = answers["command"]
    else:
        command = sys.argv[1]

    if command == "config":
        run_config_interactive()
        return

    ensure_config_exists_or_exit("cluster.py")
    global CFG
    CFG = load_config()

    if command == "render":
        infra = select_infra()
        if not infra:
            print("No infrastructure selected. Exiting.")
            return

        release_image = get_release_image()
        access_mode = select_access_mode()
        control_plane, infrastructure = select_replica_mode()
        cp_version = select_control_plane_version()

        questions = [inquirer.Confirm("local_cpo", message="Use local control plane operator?", default=False)]
        local_cpo_answers = safe_prompt(questions)
        local_cpo = local_cpo_answers["local_cpo"]

        questions = [inquirer.Text("node_count", message="Enter number of nodes", default="2"),
                     inquirer.Text("instance_type", message="Enter instance type", default="m6i.xlarge")]
        node_answers = safe_prompt(questions)
        node_count = node_answers["node_count"]
        instance_type = node_answers["instance_type"]

        render_cluster_yaml(infra, release_image, access_mode, control_plane, infrastructure, cp_version, local_cpo, node_count, instance_type)
    
    elif command == "apply":
        apply_cluster_yaml()
    
    elif command == "k":
        create_kubeconfig()
    
    elif command == "rm":
        delete_hosted_cluster()
    
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