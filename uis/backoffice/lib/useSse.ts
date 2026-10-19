// lib/useSse.ts
//
// React hook over lib/sse.ts: subscribes to a named event of the API's SSE stream while the
// component is mounted and reports the connection status. Unmounting aborts the request.

import { useEffect, useRef, useState } from "react";
import { connectSse, type SseStatus } from "./sse";

interface UseSseOptions {
  path: string;
  eventName: string;
  onEvent: (data: unknown) => void;
  // Runs each time the stream reconnects (not on the first connection): refetch what was missed.
  onReconnect?: () => void;
}

export function useSse({ path, eventName, onEvent, onReconnect }: UseSseOptions): SseStatus {
  const [status, setStatus] = useState<SseStatus>("connecting");

  // The connection must not restart when the caller passes new callback instances, so it
  // always calls the latest ones through a ref.
  const handlers = useRef({ onEvent, onReconnect });
  useEffect(() => {
    handlers.current = { onEvent, onReconnect };
  });

  useEffect(
    () =>
      connectSse({
        path,
        eventName,
        onEvent: (data) => handlers.current.onEvent(data),
        onReconnect: () => handlers.current.onReconnect?.(),
        onStatus: setStatus,
      }),
    [path, eventName],
  );

  return status;
}
