/**
 * Shared "Triggered" column renderer (#65).
 *
 * The Queue tab and the Compile-History dialog both need a cell that
 * answers "who kicked this compile off?". Before DRYing this up, the
 * two surfaces drifted:
 *   - Queue: icons + rich labels ("HA action" / "API" / "Manual" /
 *     cron human string).
 *   - History: plain text ("HA" / "User" / "Scheduled·1x").
 *
 * This helper returns the icon + label pair for the four trigger
 * sources we care about. Consumers can render the simple badge
 * directly (history) or compose extra detail around it (queue adds
 * the cron schedule string for recurring jobs).
 */

import type { ReactNode } from 'react';
import { Calendar, Clock, HomeIcon, Terminal, User } from 'lucide-react';


export type TriggerSourceShape = {
  ha_action?: boolean;
  api_triggered?: boolean;
  scheduled?: boolean;
  schedule_kind?: 'recurring' | 'once' | null | string;
  // History rows use ``triggered_by`` + ``trigger_detail`` strings
  // from the DB instead of the Queue's per-flag booleans. Accept
  // either; the helper normalises.
  triggered_by?: 'user' | 'ha_action' | 'api' | 'schedule' | null | string;
  trigger_detail?: string | null;
};


export type TriggerSource = 'user' | 'ha_action' | 'api' | 'schedule_once' | 'schedule_recurring';


export function classifyTrigger(row: TriggerSourceShape): TriggerSource {
  // Queue-row shape: booleans.
  if (row.ha_action) return 'ha_action';
  if (row.api_triggered) return 'api';
  if (row.scheduled) {
    return row.schedule_kind === 'once' ? 'schedule_once' : 'schedule_recurring';
  }
  // History-row shape: triggered_by string.
  if (row.triggered_by === 'ha_action') return 'ha_action';
  if (row.triggered_by === 'api') return 'api';
  if (row.triggered_by === 'schedule') {
    return row.trigger_detail === 'once' ? 'schedule_once' : 'schedule_recurring';
  }
  return 'user';
}


export interface TriggerBadge {
  icon: ReactNode;
  label: string;
  title: string;
}


/**
 * Compact badge for the Triggered column — same icon + label across
 * Queue and History. The Queue tab adds the cron-string detail to
 * the recurring/once variants in its own renderer; this helper
 * carries only the shared icon + label.
 */
export function getTriggerBadge(row: TriggerSourceShape): TriggerBadge {
  const source = classifyTrigger(row);
  switch (source) {
    case 'ha_action':
      return {
        icon: <HomeIcon className="size-3" aria-hidden="true" />,
        label: 'HA action',
        title: 'Triggered by a Home Assistant service action (esphome_fleet.compile)',
      };
    case 'api':
      return {
        icon: <Terminal className="size-3" aria-hidden="true" />,
        label: 'API',
        title: 'Triggered by a direct API call (server-token Bearer, not the HA integration)',
      };
    case 'schedule_once':
      return {
        icon: <Calendar className="size-3" aria-hidden="true" />,
        label: 'Once',
        title: 'Triggered by a one-time schedule',
      };
    case 'schedule_recurring':
      return {
        icon: <Clock className="size-3" aria-hidden="true" />,
        label: 'Recurring',
        title: 'Triggered by a recurring cron schedule',
      };
    case 'user':
    default:
      return {
        icon: <User className="size-3" aria-hidden="true" />,
        label: 'Manual',
        title: 'Manual action (from the Fleet UI)',
      };
  }
}
