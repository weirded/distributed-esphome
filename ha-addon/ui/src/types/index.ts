export interface ServerInfo {
  token: string;
  port: number;
  server_ip?: string;
  server_addresses?: string[];
  addon_version?: string;
  server_client_version?: string;
  min_image_version?: string;
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
  /** How the IP was resolved — see Device.address_source for the value list. */
  address_source?: string | null;
  running_version?: string;
  online?: boolean | null;
  needs_update?: boolean;
  config_modified?: boolean;
  last_seen?: string;
  compilation_time?: number;
  server_version?: string;
  has_api_key?: boolean;
  has_web_server?: boolean;
  /**
   * #14: true if the resolved YAML has a ``button: - platform: restart``
   * entry. Used to gray out the Restart menu item when no such button
   * exists, instead of letting the click fail.
   */
  has_restart_button?: boolean;
  ha_configured?: boolean;
  ha_connected?: boolean | null;
  /**
   * HA device registry ID — present when we matched the device to HA by MAC.
   * Used by the UI to deep-link the HA column to /config/devices/device/<id>.
   * (#35)
   */
  ha_device_id?: string | null;
  /**
   * Primary network connectivity block (#10). Mirrors ESPHome's own
   * resolver precedence: wifi → ethernet → openthread. Null when none of
   * the three blocks is present in the resolved config.
   */
  network_type?: 'wifi' | 'ethernet' | 'thread' | null;
  /** Any of the connectivity blocks declared a manual_ip.static_ip. */
  network_static_ip?: boolean;
  /** Top-level ``network: {enable_ipv6: true}`` in the resolved config. */
  network_ipv6?: boolean;
  /** wifi.ap fallback access point configured. */
  network_ap_fallback?: boolean;
  /**
   * True when the device participates in Matter — either an explicit
   * top-level ``matter:`` block, or an ``openthread:`` block (ESPHome's
   * openthread component only exists for Matter support, so the latter
   * is treated as a Matter signal too).
   */
  network_matter?: boolean;
  /** Per-device pinned ESPHome version from YAML metadata comment. */
  pinned_version?: string | null;
  /** Cron schedule expression (5-field). */
  schedule?: string | null;
  /** Whether the schedule is active. */
  schedule_enabled?: boolean;
  /** ISO datetime of last scheduled run. */
  schedule_last_run?: string | null;
  /** ISO datetime for a one-time scheduled upgrade. Auto-cleared after firing. */
  schedule_once?: string | null;
  /** IANA tz name (e.g. "America/Los_Angeles") that the cron expression is
   * interpreted in. Absent for legacy schedules — the scheduler treats those
   * as UTC. New schedules from the UI always carry the browser tz. */
  schedule_tz?: string | null;
  /** Comma-separated tags from YAML metadata comment. */
  tags?: string | null;
}

export interface Device {
  name: string;
  mac_address?: string;
  ip_address?: string;
  running_version?: string;
  online?: boolean;
  compile_target?: string | null;
  last_seen?: string;
  compilation_time?: number;
  /**
   * How the IP address was resolved. One of: "mdns", "wifi_use_address",
   * "ethernet_use_address", "openthread_use_address", "wifi_static_ip",
   * "ethernet_static_ip", "mdns_default" (the {name}.local fallback).
   * Surfaced under the IP in the Devices tab so users can see at a glance
   * how each device's address was determined.
   */
  address_source?: string | null;
  /**
   * True when Home Assistant confirms this device exists (MAC in the HA
   * ESPHome-device MAC set, or a matching entity in the HA registry).
   * Populated for both managed and unmanaged devices — particularly
   * useful on unmanaged rows to distinguish "random mDNS broadcast" from
   * "real ESPHome device we don't have YAML for yet".
   */
  ha_configured?: boolean;
  /**
   * HA-reported connectivity: true if the device is currently reachable
   * via HA, false if not, null if HA doesn't expose a status entity for it.
   * Only meaningful when ha_configured is true.
   */
  ha_connected?: boolean | null;
  /** HA device registry ID for deep-linking. See Target.ha_device_id (#35). */
  ha_device_id?: string | null;
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
  /** Number of target build directories with cached .esphome/ artifacts. */
  cached_targets?: number;
  /** Total size of the build cache in MB. */
  cache_size_mb?: number;
}

/**
 * Fields used to pre-populate the Connect Worker modal when re-connecting
 * an existing worker (e.g. from the "Image Stale" badge). All optional —
 * missing fields fall back to the modal's default state.
 */
export interface WorkerPreset {
  hostname?: string;
  max_parallel_jobs?: number;
  host_platform?: string;
}

export interface Worker {
  client_id: string;
  hostname: string;
  online: boolean;
  disabled: boolean;
  max_parallel_jobs?: number;
  requested_max_parallel_jobs?: number | null;
  client_version?: string;
  image_version?: string | null;
  system_info?: SystemInfo;
  current_job_id?: string;
  last_seen?: string;
}

export interface Job {
  id: string;
  target: string;
  state: string;
  /** ESPHome version this job will compile against. */
  esphome_version?: string;
  assigned_client_id?: string;
  assigned_hostname?: string;
  worker_id?: number | null;
  pinned_client_id?: string;
  /**
   * #23: true when this job is a "follow-up" — created while another job
   * for the same target was already running. Follow-ups are blocked from
   * claiming until the predecessor finishes; surfaced in the queue UI as
   * a "Queued" badge so the user can see "next compile is waiting".
   */
  is_followup?: boolean;
  /** True when this job was triggered by the cron scheduler, not a manual action. */
  scheduled?: boolean;
  duration_seconds?: number | null;
  assigned_at?: string;
  created_at: string;
  finished_at?: string;
  status_text?: string;
  ota_only?: boolean;
  validate_only?: boolean;
  ota_result?: string;
  log?: string;
}
