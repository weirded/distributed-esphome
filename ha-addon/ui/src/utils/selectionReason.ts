/**
 * Bug #8 (1.6.1): consistent rendering of the worker-selection reason
 * across the live Queue, the per-device Compile-history, and the
 * fleet-wide Queue-history dialog.
 *
 * The server persists a stable wire identifier (e.g. ``"pinned_to_worker"``);
 * the UI translates it to a short pill label + a longer tooltip so a
 * hover explains the decision without forcing the column to be wide.
 *
 * UD.2: ``shortLabel`` is the compact form used at viewports below the
 * Tailwind ``xl:`` breakpoint (1280 px) where the longer wording made the
 * Worker-selection column overflow on a standard 13" laptop. The full
 * ``label`` reads better when there's room; the tooltip keeps both
 * forms unambiguous regardless of which one is on screen.
 */

export interface SelectionReasonDisplay {
  label: string;
  shortLabel: string;
  title: string;
}

export function formatSelectionReason(reason: string | null | undefined): SelectionReasonDisplay | null {
  if (!reason) return null;
  switch (reason) {
    case 'pinned_to_worker':
      // Bug #13: "Pinned" was ambiguous — users can also pin a job's
      // ESPHome version and pin a firmware variant, so a bare "Pinned"
      // pill next to a worker name still required a moment of thought.
      // Spelling out "Pinned to worker" anchors the pin to the worker.
      return {
        label: 'Pinned to worker',
        shortLabel: 'Pinned',
        title: 'Operator pinned this job to the worker from the Upgrade modal — scheduling ignored.',
      };
    case 'only_online_worker':
      return {
        label: 'Only worker online',
        shortLabel: 'Only online',
        title: 'This was the only online, eligible worker when the job was claimed.',
      };
    case 'only_eligible_worker':
      // Bug #99: distinct from 'only_online_worker'. Other workers
      // were online but the routing rules disqualified all of them
      // for this job — this worker was the only one whose tags
      // satisfied the required clause.
      return {
        label: 'Only eligible by tag',
        shortLabel: 'Only eligible',
        title: 'Other workers were online but the routing rules disqualified them for this device — this worker’s tags were the only ones that satisfied the rule.',
      };
    case 'fewer_jobs_than_others':
      return {
        label: 'Least busy worker',
        shortLabel: 'Least busy',
        title: 'This worker had fewer active jobs than every other candidate when it claimed the job.',
      };
    case 'higher_perf_score':
      // Bug #13: "Fastest" alone could read as "fastest at polling"
      // (i.e. first-come-first-served). "Fastest worker available"
      // makes the perf-score criterion explicit.
      return {
        label: 'Fastest worker available',
        shortLabel: 'Fastest',
        title: 'Tied on active-job count with the other candidates, but had the highest effective perf score (perf × (1 − cpu load)).',
      };
    case 'first_available':
      // Already short.
      return {
        label: 'First to poll',
        shortLabel: 'First to poll',
        title: 'Multiple workers were equally eligible; this one polled the /claim endpoint first.',
      };
    default:
      return { label: reason, shortLabel: reason, title: `Unknown selection reason: ${reason}` };
  }
}
