import type { Target } from '@/types';

/**
 * Bug #32 follow-up: single source of truth for "this target's YAML
 * differs from what's on the device."
 *
 * Precedence:
 *   1. `config_drifted_since_flash` (git diff of YAML between the
 *      HEAD at last successful flash and current HEAD) — precise;
 *      survives mtime-churn from `git checkout` / editor autosaves.
 *   2. `config_modified` — on a git repo this reflects `git status`
 *      (uncommitted local edits); on a non-repo config dir it falls
 *      back to `yaml.mtime > device.compilation_time`.
 *
 * Both the Upgrade button color and the "config changed" badge in the
 * ESPHome column use this — they were reading different signals before,
 * which let the badge fire on mtime churn even when git said clean.
 */
export function hasDriftedConfig(t: Pick<Target, 'config_drifted_since_flash' | 'config_modified'>): boolean {
  return t.config_drifted_since_flash === true
    || (t.config_drifted_since_flash == null && t.config_modified === true);
}

/** Human-readable explanation for the "config changed" indicator's tooltip. */
export function driftTooltip(t: Pick<Target, 'config_drifted_since_flash' | 'config_modified'>): string | undefined {
  if (t.config_drifted_since_flash === true) {
    return 'YAML has changed since this device was last flashed — Upgrade to apply.';
  }
  if (t.config_drifted_since_flash == null && t.config_modified === true) {
    return 'YAML has uncommitted local changes (git status).';
  }
  return undefined;
}
