/**
 * Shared sortable table header (QS.21).
 *
 * Used in the <th> of TanStack Table headers across the Devices, Queue, and
 * Schedules tabs. Deduplicates three byte-identical copies that each rendered
 * the click target as a <span onClick> with no accessible role or sort state.
 *
 * The click target is now a real <button> (semantic HTML) and the parent <th>
 * should set `aria-sort` via {@link getAriaSort} — WAI-ARIA requires aria-sort
 * on the element with role="columnheader" (implicit on <th>), not on a child.
 */

type SortState = false | 'asc' | 'desc';

interface SortableColumn {
  getIsSorted: () => SortState;
  toggleSorting: (desc?: boolean) => void;
  getCanSort: () => boolean;
}

export function SortHeader({ label, column }: { label: string; column: SortableColumn }) {
  const sorted = column.getIsSorted();
  const indicator = sorted === 'asc' ? ' \u25b2' : sorted === 'desc' ? ' \u25bc' : '';
  const title =
    sorted === 'asc' ? 'Click to sort descending'
    : sorted === 'desc' ? 'Click to reset sort'
    : 'Click to sort ascending';
  return (
    <button
      type="button"
      onClick={() => column.toggleSorting(sorted === 'asc')}
      title={title}
      className="cursor-pointer select-none bg-transparent border-0 p-0 font-inherit text-inherit"
    >
      {label}{indicator}
    </button>
  );
}

/** Map a TanStack column's sort state to the WAI-ARIA aria-sort attribute. */
export function getAriaSort(column: SortableColumn): 'ascending' | 'descending' | 'none' {
  const sorted = column.getIsSorted();
  if (sorted === 'asc') return 'ascending';
  if (sorted === 'desc') return 'descending';
  return 'none';
}
