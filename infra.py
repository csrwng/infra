import os
import sys
import shutil
import subprocess
import inquirer
import random
import string
import json
from config import ensure_config_exists_or_exit, load_config, run_config_interactive

CFG = None

def generate_random_string(length=6):
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choices(characters, k=length))

def execute_command(command):
    """Executes a shell command and streams output."""
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(line, end="")  # Stream output
    process.wait()
    return process.returncode

def list_infra():
    """Lists all infrastructure directories."""
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

def create_infra():
    """Handles infrastructure creation."""
    questions = [
        inquirer.Text("name", message="Name", default=CFG.get("name", "")),
        inquirer.Text("region", message="Region", default=CFG.get("region", "")),
        inquirer.Text("base_domain", message="Base Domain", default=CFG.get("base_domain", "")),
        inquirer.List("external_connectivity", message="External Traffic",
                      choices=["Public", "Proxy", "SecureProxy", "NAT gateway"])
    ]
    
    answers = inquirer.prompt(questions)
    if not answers:
        print("Operation cancelled.")
        return
    
    infra_dir = CFG.get("infra_dir")
    infra_path = os.path.join(infra_dir, answers["name"])
    
    if os.path.exists(infra_path):
        print(f"Error: Infrastructure '{answers['name']}' already exists.")
        return
    
    os.makedirs(infra_path)
    print(f"Created directory: {infra_path}")

    hypershift_command = CFG.get("hypershift_path", "hypershift")
    suffix = generate_random_string()
    infra_id = f"{answers['name']}-{suffix}"
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
        file.write(f"{answers['name']}")

    with open(infraid_out, "w") as file:
        file.write(f"{infra_id}")
    
    command = f"{hypershift_command} create infra aws \
  --aws-creds {CFG.get('aws_creds_path')} \
  --base-domain {answers['base_domain']} \
  --infra-id {infra_id} \
  --name {answers['name']} \
  --region {answers['region']} \
  {connectivity_flag_mapping[answers['external_connectivity']]} \
  --output-file {infra_out} && \
  {hypershift_command} create iam aws \
  --aws-creds {CFG.get('aws_creds_path')} \
  --infra-id {infra_id} \
  --oidc-storage-provider-s3-bucket-name {CFG.get('oidc_s3_bucket_name')} \
  --oidc-storage-provider-s3-region {CFG.get('oidc_s3_region')} \
  --region {answers['region']} \
  --local-zone-id $(jq -r '.localZoneID' {infra_out}) \
  --public-zone-id $(jq -r '.publicZoneID' {infra_out}) \
  --private-zone-id $(jq -r '.privateZoneID' {infra_out}) \
  --output-file {iam_out}"
    
    print("Executing:", command)
    
    if execute_command(command) == 0:
        print("Infrastructure created successfully.")
    else:
        print("Failed to create infrastructure.")

def destroy_infra():
    """Handles infrastructure destruction."""
    infra_list = list_infra()
    
    if not infra_list:
        return
    
    questions = [
        inquirer.List("infra_name", message="Select infrastructure to destroy", choices=infra_list)
    ]
    answer = inquirer.prompt(questions)
    
    if not answer:
        print("Operation cancelled.")
        return
    
    infra_name = answer["infra_name"]
    infra_dir = CFG.get("infra_dir")
    infra_path = os.path.join(infra_dir, infra_name)
    infra_out = os.path.join(infra_path, "infra.json")
    iam_out = os.path.join(infra_path, "iam.json")
    success = True
    
    if os.path.exists(infra_out):
        with open(infra_out, "r") as file:
            data = json.load(file)  # Parse JSON into a dictionary

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
            data = json.load(file)  # Parse JSON into a dictionary

        command = f"hypershift destroy iam aws --infra-id={data.get('infraID')} --aws-creds {CFG.get('aws_creds_path')} --region={data.get('region')}"
        print("Executing:", command)
    
        if execute_command(command) == 0:
            print(f"IAM for '{infra_name}' destroyed.")
        else:
            print("Failed to destroy IAM.")
            success = False
    
    if success:
        shutil.rmtree(infra_path)

def main():
    """Main function to handle command-line arguments."""
    if len(sys.argv) > 1:
        command = sys.argv[1]
    else:
        questions = [
            inquirer.List("command", message="Select a command", choices=["create", "destroy", "list", "config"])
        ]
        answers = inquirer.prompt(questions)
        if not answers:
            print("Operation cancelled.")
            return
        command = answers["command"]
    
    if command == "config":
        run_config_interactive()
        return

    # Ensure config exists for all other commands
    ensure_config_exists_or_exit("infra.py")
    global CFG
    CFG = load_config()

    if command == "create":
        create_infra()
    elif command == "destroy":
        destroy_infra()
    elif command == "list":
        list_infra()
    else:
        print("Invalid command. Use 'create', 'destroy', 'list', or 'config'.")

if __name__ == "__main__":
    main()