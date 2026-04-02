import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Polls an async fetcher function at a fixed interval.
 * The first call fires immediately on mount.
 * Returns the latest successful result (null until first successful fetch).
 * Skips a cycle if the previous fetch is still in flight (prevents request pileup).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): T | null {
  const [data, setData] = useState<T | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const inFlightRef = useRef(false);

  const run = useCallback(async () => {
    if (inFlightRef.current) return; // skip if previous fetch still running
    inFlightRef.current = true;
    try {
      const result = await fetcherRef.current();
      setData(result);
    } catch {
      // Silently ignore network errors — the UI stays on stale data
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    run();
    const id = setInterval(run, intervalMs);
    return () => clearInterval(id);
  }, [run, intervalMs]);

  return data;
}
