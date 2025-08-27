## Infra CLI for HyperShift on AWS

Tools to create/destroy AWS infrastructure for HyperShift and to render/apply HostedCluster manifests. Two entrypoints:

- `infra.py`: manage cloud infra and IAM using the HyperShift CLI
- `cluster.py`: render/apply HostedCluster YAML, manage kubeconfigs, and delete clusters

### Prerequisites

- Python 3.10+
- macOS or Linux shell
- CLI tools installed and on your PATH (or provide paths via config):
  - HyperShift CLI (`hypershift`)
  - OpenShift CLI (`oc`)
  - `jq`
  - `git` (only needed when using local CPO image option)
- AWS credentials with sufficient permissions to create/destroy infra and IAM

### Quick start

1) Clone and set up a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) Create or update local config

Configuration is stored at `~/.infra/config.json`.

```bash
infra config
# or
hc config
```

You will be prompted for:

- Default `name`, `region`, `base_domain`
- Paths: `hypershift_path`, `infra_dir`, `aws_creds_path`, `pull_secret_path`, `kubeconfig_dir`
- OIDC S3 settings: `oidc_s3_bucket_name`, `oidc_s3_region`
- Optional: `external_dns_domain`, `hypershift_repo_dir`, `local_cpo_image_prefix`

3) Use the CLIs

Infra management (`infra.py`):

```bash
# Create infra (interactive prompts)
infra create

# List created infrastructures
infra list

# Destroy infra (interactive selection)
infra destroy
```

### Easier invocation options

- Option A: local wrapper scripts (no packaging)

  The repo includes `bin/infra` and `bin/hc` which will use `.venv` if present or fall back to `python3`.
  You can run them directly or add to your PATH:

  ```bash
  # from repo root
  ./bin/infra list
  ./bin/hc list

  # or make available globally
  export PATH="$PWD/bin:$PATH"
  infra list
  hc list
  ```

- Option B: install as a package with console scripts

  Install in editable mode to get `infra` and `hc` commands everywhere:

  ```bash
  pip install -r requirements.txt
  pip install -e .
  # then
  infra list
  hc list
  ```

  This uses the console entry points defined in `pyproject.toml` mapping `infra` → `infra:main` and `hc` → `cluster:main`.

Cluster workflow (`cluster.py`):

```bash
# Render cluster.yaml for a chosen infra and release image
hc render

# Apply previously rendered YAML
hc apply

# Generate a kubeconfig for a HostedCluster
hc k

# Delete a HostedCluster
hc rm

# List HostedClusters
hc list
```

### How it works

- `infra.py create` wraps `hypershift create infra aws` and `hypershift create iam aws`, writing outputs under the selected `infra_dir` (e.g., `infra.json`, `iam.json`).
- `infra.py destroy` reads those files and calls the matching `hypershift destroy ...` commands, then removes the infra directory.
- `cluster.py render` builds a `hypershift create cluster aws --render` command using your config and selections, writing `cluster.yaml` into the chosen infra directory.
- `cluster.py apply` runs `oc apply -f cluster.yaml`.
- `cluster.py k` writes a kubeconfig to `kubeconfig_dir` via `hypershift create kubeconfig`.

### Notes and tips

- Ensure `aws_creds_path`, `pull_secret_path`, and `infra_dir` exist and are readable/writable by your user.
- Some operations assume access to a management cluster via `oc`.
- When using the local CPO option, `hypershift_repo_dir` must be a valid git repo; the short commit hash is appended to `local_cpo_image_prefix`.

### Development

- Project is plain Python; no build step is required.
- Recommended tools are pinned by your environment; install additional dev tooling as needed.
- A `.gitignore` is included to exclude virtualenvs, caches, and OS/editor artifacts.

### License

This project is provided as-is; choose and add a license if you plan to publish.


