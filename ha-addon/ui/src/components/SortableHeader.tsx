import type { SortState } from '../hooks/useSortable';

interface Props {
  label: string;
  col: string;
  sort: SortState;
  onSort: (col: string) => void;
  style?: React.CSSProperties;
}

export function SortableHeader({ label, col, sort, onSort, style }: Props) {
  const isActive = sort.col === col && sort.dir != null;
  const indicator = isActive ? (sort.dir === 'asc' ? ' \u25b2' : ' \u25bc') : '';
  return (
    <th
      onClick={() => onSort(col)}
      style={{ cursor: 'pointer', userSelect: 'none', ...style }}
      title={isActive ? (sort.dir === 'asc' ? 'Click to sort descending' : 'Click to reset sort') : 'Click to sort ascending'}
    >
      {label}{indicator}
    </th>
  );
}
