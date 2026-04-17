/**
 * usePersistedState — tiny wrapper over useState that round-trips
 * through localStorage, used by the tabs' TanStack Table sorting state
 * (QS.27) so a chosen sort order survives page reloads.
 *
 * Keep the API stable — `App.tsx` relies on the same pattern for
 * column visibility and the theme toggle.
 */

import { useCallback, useEffect, useState } from 'react';

export function usePersistedState<T>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = typeof window !== 'undefined' ? window.localStorage.getItem(key) : null;
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // quota exceeded or private-mode — fall through; state stays
      // session-only this load.
    }
  }, [key, value]);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => setValue(next),
    [],
  );
  return [value, set];
}
