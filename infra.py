import os
import sys
import shutil
import subprocess
import inquirer
import random
import string
import json
import argparse
from config import ensure_config_exists_or_exit, load_config, run_config_interactive
from utils import safe_prompt, load_input_file, merge_inputs

CFG = None

def generate_random_string(length=6):
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choices(characters, k=length))

def execute_command(command):
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(line, end="")
    process.wait()
    return process.returncode

def list_infra():
    infra_dir = CFG.get("infra_dir")
    if not os.path.exists(infra_dir):
        os.makedirs(infra_dir)
    infra_list = sorted([d for d in os.listdir(infra_dir) if os.path.isdir(os.path.join(infra_dir, d))])

    if not infra_list:
        print("No infrastructure found.")
        return []

    for i, infra in enumerate(infra_list, start=1):
        print(f"{i}. {infra}")

    return infra_list

def create_infra(params=None):
    params = dict(params) if params else {}

    questions = []
    if "name" not in params:
        questions.append(inquirer.Text("name", message="Name", default=CFG.get("name", "")))
    if "region" not in params:
        questions.append(inquirer.Text("region", message="Region", default=CFG.get("region", "")))
    if "base_domain" not in params:
        questions.append(inquirer.Text("base_domain", message="Base Domain", default=CFG.get("base_domain", "")))
    if "external_connectivity" not in params:
        questions.append(inquirer.List("external_connectivity", message="External Traffic",
                      choices=["Public", "Proxy", "SecureProxy", "NAT gateway"]))
    if "kms_key_arn" not in params:
        if questions:
            questions.append(inquirer.Text("kms_key_arn", message="KMS Key ARN (optional)", default=""))
        else:
            params["kms_key_arn"] = ""

    if questions:
        answers = safe_prompt(questions)
        params.update(answers)

    infra_dir = CFG.get("infra_dir")
    infra_path = os.path.join(infra_dir, params["name"])

    if os.path.exists(infra_path):
        print(f"Error: Infrastructure '{params['name']}' already exists.")
        return

    os.makedirs(infra_path)
    print(f"Created directory: {infra_path}")

    hypershift_command = CFG.get("hypershift_path", "hypershift")
    suffix = generate_random_string()
    infra_id = f"{params['name']}-{suffix}"
    name_out = os.path.join(infra_path, "name")
    infraid_out = os.path.join(infra_path, "infra_id")
    infra_out = os.path.join(infra_path, "infra.json")
    iam_out = os.path.join(infra_path, "iam.json")
    connectivity_flag_mapping = {
        "Public": "--public-only",
        "Proxy": "--enable-proxy",
        "SecureProxy": "--enable-secure-proxy",
        "NAT gateway": "",
    }
    with open(name_out, "w") as file:
        file.write(f"{params['name']}")

    with open(infraid_out, "w") as file:
        file.write(f"{infra_id}")

    kms_key_flag = f" --kms-key-arn {params['kms_key_arn']}" if params.get('kms_key_arn', '').strip() else ""

    command = f"{hypershift_command} create infra aws \
  --aws-creds {CFG.get('aws_creds_path')} \
  --base-domain {params['base_domain']} \
  --infra-id {infra_id} \
  --name {params['name']} \
  --region {params['region']} \
  {connectivity_flag_mapping[params['external_connectivity']]} \
  --output-file {infra_out} && \
  {hypershift_command} create iam aws \
  --aws-creds {CFG.get('aws_creds_path')} \
  --infra-id {infra_id} \
  --oidc-storage-provider-s3-bucket-name {CFG.get('oidc_s3_bucket_name')} \
  --oidc-storage-provider-s3-region {CFG.get('oidc_s3_region')} \
  --region {params['region']} \
  --local-zone-id $(jq -r '.localZoneID' {infra_out}) \
  --public-zone-id $(jq -r '.publicZoneID' {infra_out}) \
  --private-zone-id $(jq -r '.privateZoneID' {infra_out}){kms_key_flag} \
  --output-file {iam_out}"

    print("Executing:", command)

    if execute_command(command) == 0:
        print("Infrastructure created successfully.")
    else:
        print("Failed to create infrastructure.")

def destroy_infra(params=None):
    params = dict(params) if params else {}

    if "name" in params:
        infra_name = params["name"]
        infra_dir = CFG.get("infra_dir")
        if not os.path.isdir(os.path.join(infra_dir, infra_name)):
            print(f"Error: Infrastructure '{infra_name}' not found.")
            return
    else:
        infra_list = list_infra()
        if not infra_list:
            return
        questions = [
            inquirer.List("infra_name", message="Select infrastructure to destroy", choices=infra_list)
        ]
        answer = safe_prompt(questions)
        infra_name = answer["infra_name"]

    infra_dir = CFG.get("infra_dir")
    infra_path = os.path.join(infra_dir, infra_name)
    infra_out = os.path.join(infra_path, "infra.json")
    iam_out = os.path.join(infra_path, "iam.json")
    success = True

    if os.path.exists(infra_out):
        with open(infra_out, "r") as file:
            data = json.load(file)

        command = f"hypershift destroy infra aws --infra-id={data.get('infraID')} --name={data.get('Name')} --region={data.get('region')} \
    --aws-creds {CFG.get('aws_creds_path')} \
    --base-domain={data.get('baseDomain')}"
        print("Executing:", command)

        if execute_command(command) == 0:
            print(f"Infrastructure '{infra_name}' destroyed.")
        else:
            print("Failed to destroy infrastructure.")
            success = False

    if os.path.exists(iam_out):
        with open(iam_out, "r") as file:
            data = json.load(file)

        command = f"hypershift destroy iam aws --infra-id={data.get('infraID')} --aws-creds {CFG.get('aws_creds_path')} --region={data.get('region')}"
        print("Executing:", command)

        if execute_command(command) == 0:
            print(f"IAM for '{infra_name}' destroyed.")
        else:
            print("Failed to destroy IAM.")
            success = False

    if success:
        shutil.rmtree(infra_path)

def _parse_args():
    parser = argparse.ArgumentParser(description="Manage HyperShift AWS infrastructure")
    subparsers = parser.add_subparsers(dest="command")

    create_p = subparsers.add_parser("create", help="Create AWS infrastructure")
    create_p.add_argument("-i", "--input", dest="input_file", help="Input YAML/JSON file with parameters")
    create_p.add_argument("--name", help="Infrastructure name")
    create_p.add_argument("--region", help="AWS region")
    create_p.add_argument("--base-domain", dest="base_domain", help="Base domain")
    create_p.add_argument("--external-connectivity", dest="external_connectivity",
                          choices=["Public", "Proxy", "SecureProxy", "NAT gateway"],
                          help="External traffic connectivity type")
    create_p.add_argument("--kms-key-arn", dest="kms_key_arn", help="KMS Key ARN")

    destroy_p = subparsers.add_parser("destroy", help="Destroy AWS infrastructure")
    destroy_p.add_argument("-i", "--input", dest="input_file", help="Input YAML/JSON file")
    destroy_p.add_argument("--name", help="Infrastructure name to destroy")

    subparsers.add_parser("list", help="List infrastructures")
    subparsers.add_parser("config", help="Configure settings interactively")

    return parser.parse_args()

def main():
    if len(sys.argv) < 2:
        questions = [
            inquirer.List("command", message="Select a command", choices=["create", "destroy", "list", "config"])
        ]
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

    ensure_config_exists_or_exit("infra.py")
    global CFG
    CFG = load_config()

    if command == "create":
        create_infra(params)
    elif command == "destroy":
        destroy_infra(params)
    elif command == "list":
        list_infra()
    else:
        print("Invalid command. Use 'create', 'destroy', 'list', or 'config'.")

if __name__ == "__main__":
    main()
