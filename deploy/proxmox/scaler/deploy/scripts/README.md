# Pool bootstrap (shell-script path)

If you don't want Terraform, `bootstrap-pool.sh` does the same job: clone an LXC template into a pool of N workers, idempotently.

## Use

1. SSH to your Proxmox host as root.
2. Copy `bootstrap-pool.sh` over (or pull the repo).
3. Set the env vars and run:

```bash
TEMPLATE_VMID=900 \
POOL_VMIDS="200 201 202 203 204 205" \
POOL_HOSTNAME_FMT="esphome-worker-%d" \
POOL_STORAGE=local-zfs \
POOL_BRIDGE=vmbr0 \
./bootstrap-pool.sh
```

## What it does (and doesn't)

- ✅ Clones the template `TEMPLATE_VMID` into each VMID listed in `POOL_VMIDS`.
- ✅ Sets a unique hostname per clone via `POOL_HOSTNAME_FMT`.
- ✅ Reconfigures `net0` to use `POOL_BRIDGE` with DHCP.
- ✅ Idempotent — existing VMIDs are skipped, not overwritten.
- ❌ Does NOT start the clones. The scaler handles start/stop after the pool exists.
- ❌ Does NOT create the template — that's a one-time manual step (see prerequisites in the script header).
- ❌ Does NOT create the Proxmox API token for the scaler — do that in the Proxmox UI or with `pveum`.

For an IaC-managed alternative, see `deploy/proxmox/scaler/deploy/terraform/`.
