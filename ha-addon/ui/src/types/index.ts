export interface ServerInfo {
  token: string;
  port: number;
  server_ip?: string;
  server_addresses?: string[];
  addon_version?: string;
  server_client_version?: string;
}

export interface EsphomeVersions {
  selected: string | null;
  detected: string | null;
  available: string[];
}

export interface Target {
  target: string;
  device_name?: string;
  friendly_name?: string;
  comment?: string;
  area?: string;
  project_name?: string;
  project_version?: string;
  ip_address?: string;
  running_version?: string;
  online?: boolean | null;
  needs_update?: boolean;
  config_modified?: boolean;
  last_seen?: string;
  compilation_time?: number;
  server_version?: string;
  has_api_key?: boolean;
  has_web_server?: boolean;
  ha_configured?: boolean;
  ha_connected?: boolean | null;
}

export interface Device {
  name: string;
  ip_address?: string;
  running_version?: string;
  online?: boolean;
  compile_target?: string;
  last_seen?: string;
  compilation_time?: number;
}

export interface SystemInfo {
  os_version?: string;
  cpu_model?: string;
  cpu_arch?: string;
  cpu_cores?: number;
  total_memory?: string;
  uptime?: string;
  perf_score?: number;
  cpu_usage?: number;
  disk_total?: string;
  disk_free?: string;
  disk_used_pct?: number;
}

export interface Worker {
  client_id: string;
  hostname: string;
  online: boolean;
  disabled: boolean;
  max_parallel_jobs?: number;
  requested_max_parallel_jobs?: number | null;
  client_version?: string;
  system_info?: SystemInfo;
  current_job_id?: string;
}

export interface Job {
  id: string;
  target: string;
  state: string;
  assigned_client_id?: string;
  assigned_hostname?: string;
  worker_id?: number | null;
  pinned_client_id?: string;
  duration_seconds?: number | null;
  assigned_at?: string;
  created_at: string;
  status_text?: string;
  ota_only?: boolean;
  validate_only?: boolean;
  ota_result?: string;
  log?: string;
}
