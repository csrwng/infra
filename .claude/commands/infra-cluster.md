# Infra & HostedCluster Management

Manage HyperShift AWS infrastructure and HostedCluster lifecycle non-interactively using the `infra` and `hc` CLI tools in this repository.

## Prerequisites

- Config must exist at `~/.infra/config.json` (run `infra config` or `hc config` interactively to create it if missing).
- The venv must be set up: `.venv/bin/python` in the repo root.
- Run commands via `./bin/infra` and `./bin/hc`, or directly via `.venv/bin/python infra.py` / `.venv/bin/python cluster.py`.

## Running commands non-interactively

Every subcommand accepts values as CLI flags, an input YAML/JSON file (`-i FILE`), or both (CLI flags override the file). Any value not provided will prompt interactively.

### Write a YAML input file, then pass it with `-i`

Use a temporary YAML file for complex commands:

```bash
cat > /tmp/params.yaml << 'EOF'
name: my-cluster
region: us-east-1
base_domain: example.com
external_connectivity: Public
EOF
./bin/infra create -i /tmp/params.yaml
```

### Or pass everything as CLI flags

```bash
./bin/infra create --name my-cluster --region us-east-1 --base-domain example.com --external-connectivity Public
```

---

## Command reference

### `infra create` -- Create AWS infrastructure

Creates VPC, IAM, and OIDC resources via `hypershift create infra aws` + `hypershift create iam aws`.

**CLI flags:**
| Flag | Description |
|------|-------------|
| `--name` | Infrastructure name |
| `--region` | AWS region |
| `--base-domain` | Base domain |
| `--external-connectivity` | `Public` \| `Proxy` \| `SecureProxy` \| `NAT gateway` |
| `--kms-key-arn` | KMS Key ARN (optional) |

**Input YAML keys:** `name`, `region`, `base_domain`, `external_connectivity`, `kms_key_arn`

### `infra destroy` -- Destroy infrastructure

**CLI flags:**
| Flag | Description |
|------|-------------|
| `--name` | Infrastructure name to destroy |

**Input YAML keys:** `name`

### `infra list` -- List infrastructures

No parameters needed.

---

### `hc render` -- Render cluster.yaml

Renders HostedCluster manifests via `hypershift create cluster aws --render`.

**CLI flags:**
| Flag | Description |
|------|-------------|
| `--infra` | Infrastructure name (must exist under `infra_dir`) |
| `--release-image` | Release image pullspec (mutually exclusive with `--version`) |
| `--version` | OCP major version, e.g. `4.18` or `5.0` |
| `--version-type` | `ci` \| `nightly` \| `stable` (used with `--version`) |
| `--access-mode` | `Public` \| `PublicAndPrivate` \| `Private` |
| `--control-plane-mode` | `SingleReplica` \| `HighlyAvailable` |
| `--infrastructure-mode` | `SingleReplica` \| `HighlyAvailable` |
| `--cp-version` | `v1` \| `v2` |
| `--local-cpo` / `--no-local-cpo` | Use local control plane operator image |
| `--node-count` | Number of worker nodes (default: `2`) |
| `--instance-type` | EC2 instance type (default: `m6i.xlarge`) |

**Input YAML keys:** `infra`, `release_image`, `version`, `version_type`, `access_mode`, `control_plane_mode`, `infrastructure_mode`, `cp_version`, `local_cpo`, `node_count`, `instance_type`

**Input YAML example (full):**
```yaml
infra: my-cluster
version: "4.18"
version_type: stable
access_mode: Public
control_plane_mode: SingleReplica
infrastructure_mode: SingleReplica
cp_version: v2
local_cpo: false
node_count: 2
instance_type: m6i.xlarge
```

### `hc apply` -- Apply rendered cluster.yaml

**CLI flags:**
| Flag | Description |
|------|-------------|
| `--infra` | Infrastructure name (must have a `cluster.yaml`) |

**Input YAML keys:** `infra`

### `hc k` -- Generate kubeconfig

**CLI flags:**
| Flag | Description |
|------|-------------|
| `--cluster` | HostedCluster name |
| `--kubeconfig-name` | Output kubeconfig file name |

**Input YAML keys:** `cluster`, `kubeconfig_name`

### `hc rm` -- Delete a HostedCluster

**CLI flags:**
| Flag | Description |
|------|-------------|
| `--cluster` | HostedCluster name |

**Input YAML keys:** `cluster`

### `hc list` -- List HostedClusters

No parameters needed.

---

## Typical end-to-end workflow

1. **Create infrastructure:**
   ```bash
   ./bin/infra create --name dev1 --region us-east-1 --base-domain example.com --external-connectivity Public
   ```

2. **Render cluster manifests:**
   ```bash
   ./bin/hc render --infra dev1 --version 4.18 --version-type stable \
     --access-mode Public --control-plane-mode SingleReplica \
     --infrastructure-mode SingleReplica --cp-version v2 \
     --no-local-cpo --node-count 2 --instance-type m6i.xlarge
   ```

3. **Apply to management cluster:**
   ```bash
   ./bin/hc apply --infra dev1
   ```

4. **Get kubeconfig:**
   ```bash
   ./bin/hc k --cluster dev1 --kubeconfig-name dev1
   ```

5. **When done -- delete cluster then destroy infra:**
   ```bash
   ./bin/hc rm --cluster dev1
   ./bin/infra destroy --name dev1
   ```

## Instructions for the agent

When the user asks to create infrastructure or provision a HostedCluster:

1. Read the existing config to understand defaults: check `~/.infra/config.json` (or the XDG path).
2. Ask the user for any values they haven't specified. Use sensible defaults where possible (Public access, SingleReplica, v2, no local CPO, 2 nodes, m6i.xlarge).
3. Write a YAML input file to `/tmp/` with the resolved parameters.
4. Run the appropriate command(s) with `-i` pointing to that file.
5. For the full workflow (infra + render + apply), run the steps sequentially -- each depends on the previous one succeeding.
6. After `hc apply`, the cluster takes several minutes to become available. Use `hc list` or `oc get hc -n clusters` to check status.
