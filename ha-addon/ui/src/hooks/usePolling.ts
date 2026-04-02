import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Polls an async fetcher function at a fixed interval.
 * The first call fires immediately on mount.
 * Returns the latest successful result (null until first successful fetch).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): T | null {
  const [data, setData] = useState<T | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
    } catch {
      // Silently ignore network errors — the UI stays on stale data
    }
  }, []);

  useEffect(() => {
    run();
    const id = setInterval(run, intervalMs);
    return () => clearInterval(id);
  }, [run, intervalMs]);

  return data;
}
