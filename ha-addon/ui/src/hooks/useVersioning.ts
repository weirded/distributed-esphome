import useSWR from 'swr';

import { getSettings, type AppSettings } from '../api/client';

/**
 * Bugs #111/#112: shared read of `appSettings.versioning_enabled` so the
 * five UI surfaces that lead to the History drawer (Devices hamburger,
 * Editor toolbar, Queue commit column, Compile-History commit column,
 * LogModal's "diff since this compile" button) can gate themselves on
 * whether versioning is actually on.
 *
 * Returns `true` only when the server has confirmed versioning is `'on'`.
 * While settings are still loading the hook returns `false` — that's the
 * correct default for gating because we'd rather briefly hide a hash
 * column than briefly show a dead link.
 */
export function useVersioningEnabled(): boolean {
  const { data } = useSWR<AppSettings>('settings', getSettings);
  return data?.versioning_enabled === 'on';
}
