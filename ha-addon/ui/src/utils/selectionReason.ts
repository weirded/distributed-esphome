/**
 * Bug #8 (1.6.1): consistent rendering of the worker-selection reason
 * across the live Queue, the per-device Compile-history, and the
 * fleet-wide Queue-history dialog.
 *
 * The server persists a stable wire identifier (e.g. ``"pinned_to_worker"``);
 * the UI translates it to a short pill label + a longer tooltip so a
 * hover explains the decision without forcing the column to be wide.
 */

export interface SelectionReasonDisplay {
  label: string;
  title: string;
}

export function formatSelectionReason(reason: string | null | undefined): SelectionReasonDisplay | null {
  if (!reason) return null;
  switch (reason) {
    case 'pinned_to_worker':
      return {
        label: 'Pinned',
        title: 'Operator pinned this job to the worker from the Upgrade modal.',
      };
    case 'only_online_worker':
      return {
        label: 'Only worker',
        title: 'This was the only online, eligible worker when the job was claimed.',
      };
    case 'fewer_jobs_than_others':
      return {
        label: 'Fewest jobs',
        title: 'This worker had fewer active jobs than every other candidate when it claimed the job.',
      };
    case 'higher_perf_score':
      return {
        label: 'Fastest',
        title: 'Tied on active-job count with the other candidates, but had the highest effective perf score (perf × (1 − cpu load)).',
      };
    case 'first_available':
      return {
        label: 'FCFS',
        title: 'Multiple workers were equally eligible; this one polled the /claim endpoint first.',
      };
    default:
      return { label: reason, title: `Unknown selection reason: ${reason}` };
  }
}
