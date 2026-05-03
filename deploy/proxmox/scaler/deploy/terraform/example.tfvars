proxmox_endpoint  = "https://proxmox.example.com:8006"
proxmox_api_token = "terraform@pve!provisioner=00000000-0000-0000-0000-000000000000"  # sensitive
proxmox_node      = "pve"
proxmox_insecure  = false  # flip true if your Proxmox uses a self-signed cert

template_vmid     = 900
pool_size         = 6
first_vmid        = 200
hostname_prefix   = "esphome-worker"

storage           = "local-zfs"
bridge            = "vmbr0"
full_clone        = true

cores             = 2
memory_mb         = 2048
swap_mb           = 512

tags              = ["esphome-fleet", "managed-by-terraform"]
