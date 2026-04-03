import { useState } from 'react';

export interface SortState {
  col: string;
  dir: 'asc' | 'desc' | null;
}

export interface UseSortableReturn {
  sort: SortState;
  handleSort: (col: string) => void;
  sortedItems: <T>(items: T[], getValue: (item: T) => string | number | null | undefined) => T[];
}

export function useSortable(defaultCol?: string): UseSortableReturn {
  const [sort, setSort] = useState<SortState>({
    col: defaultCol ?? '',
    dir: defaultCol ? 'asc' : null,
  });

  function handleSort(col: string) {
    setSort(prev => {
      if (prev.col !== col) return { col, dir: 'asc' };
      if (prev.dir === 'asc') return { col, dir: 'desc' };
      if (prev.dir === 'desc') return { col: defaultCol ?? '', dir: defaultCol ? 'asc' : null };
      return { col, dir: 'asc' };
    });
  }

  function sortedItems<T>(
    items: T[],
    getValue: (item: T) => string | number | null | undefined,
  ): T[] {
    if (!sort.dir) return items;
    return [...items].sort((a, b) => {
      const av = getValue(a) ?? '';
      const bv = getValue(b) ?? '';
      const cmp =
        typeof av === 'number' && typeof bv === 'number'
          ? av - bv
          : String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' });
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }

  return { sort, handleSort, sortedItems };
}
