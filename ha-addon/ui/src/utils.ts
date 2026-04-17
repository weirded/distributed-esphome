/**
 * Barrel re-export for the old utils grab-bag (QS.23).
 *
 * The implementations moved into three focused modules:
 *   - `utils/format.ts`   — timeAgo, stripYaml, fmtDuration, haDeepLink
 *   - `utils/cron.ts`     — formatCronHuman
 *   - `utils/jobState.ts` — isJob*, getJobBadge
 *
 * This file keeps existing `from '../utils'` imports working so the split
 * is a no-op at callsites. New code should import directly from the
 * submodule (clearer, and allows tree-shaking to drop unused clusters).
 */

export { timeAgo, stripYaml, fmtDuration, haDeepLink } from './utils/format';
export { formatCronHuman } from './utils/cron';
export { usePersistedState } from './utils/persistState';
export {
  isJobSuccessful,
  isJobInProgress,
  isJobFailed,
  isJobCancelled,
  isJobFinished,
  isJobRetryable,
  getJobBadge,
} from './utils/jobState';
