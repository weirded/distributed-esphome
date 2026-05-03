# Terraform module — Proxmox LXC worker pool

Provisions the LXC worker pool the scaler manages. Idempotent: `terraform apply` after a `pool_size` bump just adds the new clones; reducing `pool_size` removes the highest-numbered ones.

## Prerequisites

1. **A pre-built LXC template** on the Proxmox node. The scaler doesn't customize the OS — whatever you put in the template (Docker + the worker container, or a Python venv with the worker pip-installed, autostarted on boot) is what each clone inherits.
   - Quickest path: create one container manually, install + configure the worker, `pct stop <id>; pct template <id>`. Note the resulting VMID — it goes in `template_vmid`.
2. **A Proxmox API token** with permissions to create + manage containers in the target pool. In the Proxmox UI: Datacenter → Permissions → API Tokens → Add. Give it `VM.Allocate`, `VM.Config.*`, `VM.PowerMgmt`, and `Datastore.AllocateSpace` on the relevant containers/storage. Save the resulting `<user>@<realm>!<token>=<secret>` string into `proxmox_api_token`.

## Use

```bash
cd deploy/proxmox/scaler/deploy/terraform
cp example.tfvars terraform.tfvars   # then fill in real values
terraform init
terraform plan
terraform apply
```

After apply:

```bash
terraform output scaler_env_snippet
```

Paste that into your scaler's `config.env`. Add the `PROXMOX_SCALER_FLEET_*` and `PROXMOX_SCALER_PROXMOX_TOKEN_*` lines yourself — they aren't in Terraform state by design (token rotation shouldn't drift Terraform).

## Resizing the pool

- **Grow**: bump `pool_size`, run `terraform apply`. New VMIDs (`first_vmid + pool_size_old` through `first_vmid + pool_size_new - 1`) are created. Update the scaler's `PROXMOX_SCALER_VMIDS` to include the new VMIDs.
- **Shrink**: lower `pool_size`, run `terraform apply`. Terraform destroys the highest-numbered VMIDs. Make sure they're stopped first (or set the scaler's `MIN_WORKERS` low enough that they'd already be stopped).

## What this module does NOT do

- **Provision the template.** That's a one-time operator task; baking a template via Terraform is doable but bloats the module and makes worker-image updates require Terraform runs.
- **Run the scaler.** Use the Dockerfile or systemd unit at `deploy/proxmox/scaler/`.
- **Create API tokens or RBAC.** The provider needs a token to authenticate; the module can't bootstrap its own auth. Create the token in the Proxmox UI once.
- **Manage the per-LXC worker config (SERVER_URL, SERVER_TOKEN, etc.).** That lives in the template — bake it in once. Rotating the Fleet token means updating the template, not Terraform.

## Provider notes

This module uses `bpg/proxmox` (`~> 0.66`). The older `telmate/proxmox` provider works too in principle but its container support is less complete; we picked `bpg` because it's actively maintained and has first-class LXC clone support.
