output "vmids" {
  description = "All VMIDs in the pool. Feed this list (comma-joined) into PROXMOX_SCALER_VMIDS."
  value       = local.vmids
}

output "vmids_csv" {
  description = "Comma-separated VMID list, ready to paste into the scaler's config.env."
  value       = join(",", [for v in local.vmids : tostring(v)])
}

output "hostnames" {
  description = "Hostnames assigned to each LXC, in pool order."
  value       = [for c in proxmox_virtual_environment_container.worker : c.initialization[0].hostname]
}

output "scaler_env_snippet" {
  description = "Drop-in snippet for the scaler's config.env."
  value       = <<-EOT
    PROXMOX_SCALER_PROXMOX_HOST=${replace(replace(var.proxmox_endpoint, "https://", ""), "http://", "")}
    PROXMOX_SCALER_PROXMOX_NODE=${var.proxmox_node}
    PROXMOX_SCALER_VMIDS=${join(",", [for v in local.vmids : tostring(v)])}
    PROXMOX_SCALER_MIN_WORKERS=1
    PROXMOX_SCALER_MAX_WORKERS=${var.pool_size}
    PROXMOX_SCALER_TARGET_PER_WORKER=2
    PROXMOX_SCALER_POLL_INTERVAL=30
    PROXMOX_SCALER_COOLDOWN_SECONDS=600
  EOT
}
