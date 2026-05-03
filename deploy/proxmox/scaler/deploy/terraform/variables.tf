variable "proxmox_endpoint" {
  description = "Proxmox VE API endpoint, e.g. https://proxmox.example.com:8006"
  type        = string
}

variable "proxmox_api_token" {
  description = "Proxmox API token in the form '<user>@<realm>!<tokenname>=<secret>' (sensitive)."
  type        = string
  sensitive   = true
}

variable "proxmox_node" {
  description = "Proxmox node to host the LXC pool, e.g. 'pve'."
  type        = string
}

variable "proxmox_insecure" {
  description = "Skip TLS verification on Proxmox API. Set true only for self-signed certs."
  type        = bool
  default     = false
}

variable "template_vmid" {
  description = "VMID of the source LXC template to clone from. Pre-create this once with worker autostart configured."
  type        = number
}

variable "pool_size" {
  description = "Number of LXC workers in the pool. Must be >= scaler max_workers."
  type        = number
  default     = 6

  validation {
    condition     = var.pool_size >= 1 && var.pool_size <= 64
    error_message = "pool_size must be between 1 and 64."
  }
}

variable "first_vmid" {
  description = "Starting VMID for the pool. e.g. 200 → 200, 201, 202, …"
  type        = number
  default     = 200
}

variable "hostname_prefix" {
  description = "Hostname prefix for cloned LXCs. Final hostname = <prefix>-<index>."
  type        = string
  default     = "esphome-worker"
}

variable "storage" {
  description = "Proxmox storage pool for LXC root disks."
  type        = string
  default     = "local-lvm"
}

variable "bridge" {
  description = "Linux bridge for LXC network."
  type        = string
  default     = "vmbr0"
}

variable "full_clone" {
  description = "Use full clones (independent storage) vs linked clones (shared base, faster)."
  type        = bool
  default     = true
}

variable "cores" {
  description = "vCPUs per LXC."
  type        = number
  default     = 2
}

variable "memory_mb" {
  description = "Memory per LXC, in MB."
  type        = number
  default     = 2048
}

variable "swap_mb" {
  description = "Swap per LXC, in MB. 0 disables swap."
  type        = number
  default     = 512
}

variable "tags" {
  description = "Proxmox tags applied to every LXC in the pool."
  type        = list(string)
  default     = ["esphome-fleet", "managed-by-terraform"]
}
