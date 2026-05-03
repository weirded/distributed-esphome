provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.proxmox_api_token
  insecure  = var.proxmox_insecure
}

locals {
  vmids = [for i in range(var.pool_size) : var.first_vmid + i]
}

# One Container resource per VMID. The scaler manages start/stop after creation.
# We provision them in stopped state (`started = false`) so creation doesn't
# fight with the scaler's reconciliation loop on first apply.
resource "proxmox_virtual_environment_container" "worker" {
  for_each = { for i, vmid in local.vmids : tostring(vmid) => { index = i, vmid = vmid } }

  node_name = var.proxmox_node
  vm_id     = each.value.vmid
  tags      = var.tags
  started   = false

  # Clone from the template instead of declaring a fresh OS template — keeps
  # the worker image + autostart config the operator baked into the template.
  clone {
    vm_id = var.template_vmid
    full  = var.full_clone
  }

  initialization {
    hostname = "${var.hostname_prefix}-${each.value.index + 1}"

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
  }

  cpu {
    cores = var.cores
  }

  memory {
    dedicated = var.memory_mb
    swap      = var.swap_mb
  }

  disk {
    datastore_id = var.storage
  }

  network_interface {
    name   = "eth0"
    bridge = var.bridge
  }

  # Most worker images need /tmp + the docker daemon to start cleanly. If your
  # template has Docker baked in, bump this so first-boot install scripts
  # complete before the scaler tries to start the LXC for real.
  startup {
    order = 1
  }
}
