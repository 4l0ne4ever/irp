import { useEffect, useRef } from "react";

/**
 * Connect to WebSocket; invoke onMessage with parsed JSON objects.
 * Reconnects on close/error with capped exponential backoff.
 */
export function useWebSocket(url, onMessage) {
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let ws;
    let stopped = false;
    let attempt = 0;
    let timer;

    const connect = () => {
      if (stopped) return;
      try {
        ws = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        attempt = 0;
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          onMessageRef.current(data);
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (!stopped) scheduleReconnect();
      };
      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      };
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      const delay = Math.min(30000, 800 * Math.pow(2, attempt));
      attempt += 1;
      timer = setTimeout(connect, delay);
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, [url]);
}
