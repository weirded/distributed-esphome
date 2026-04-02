import { useEffect, useRef } from 'react';
import { buildWsUrl } from '../api/client';

interface UseWebSocketOptions {
  path: string;
  enabled: boolean;
  onMessage: (data: string) => void;
  onError?: () => void;
  onClose?: () => void;
}

/**
 * Manages a WebSocket connection for the given path (relative, under ui/api/).
 * Automatically closes and cleans up when disabled or on unmount.
 */
export function useWebSocket({
  path,
  enabled,
  onMessage,
  onError,
  onClose,
}: UseWebSocketOptions): void {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);
  const onCloseRef = useRef(onClose);
  onMessageRef.current = onMessage;
  onErrorRef.current = onError;
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!enabled) {
      if (wsRef.current) {
        try { wsRef.current.close(); } catch { /* ignore */ }
        wsRef.current = null;
      }
      return;
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(buildWsUrl(path));
    } catch {
      onErrorRef.current?.();
      return;
    }

    ws.onmessage = (e) => onMessageRef.current(e.data as string);
    ws.onerror = () => {
      onErrorRef.current?.();
    };
    ws.onclose = () => {
      wsRef.current = null;
      onCloseRef.current?.();
    };

    wsRef.current = ws;

    return () => {
      try { ws.close(); } catch { /* ignore */ }
      wsRef.current = null;
    };
  }, [enabled, path]);
}
