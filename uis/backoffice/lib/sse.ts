// lib/sse.ts
//
// Framework-free client for the API's Server-Sent Events stream (GET /events/stream).
//
// Why fetch and not EventSource: the stream is protected by the same JWT as the rest of the
// backoffice, and EventSource cannot send an `Authorization` header. fetch + ReadableStream can.
//
// What it does:
//  - sends `Authorization: Bearer <token>` the same way lib/api.ts does (401 -> clear token, go to /login)
//  - parses frames with SseParser, so chunks split anywhere are handled
//  - remembers the last `id:` it saw and sends it as `Last-Event-ID` when it reconnects
//  - reconnects with exponential backoff: 1s, 2s, 4s ... capped at 30s, reset after a good connection
//  - treats a silent connection as dead (the server sends a ": keepalive" comment every 15s)
//  - stops for good, aborting the request, when the returned function is called

import { clearToken, getToken } from "./auth";
import { SseParser } from "./sseParser";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export const INITIAL_BACKOFF_MS = 1000;
export const MAX_BACKOFF_MS = 30_000;
// The server pings every 15s; three missed pings in a row means the connection is dead.
export const STALL_TIMEOUT_MS = 45_000;

// "connecting" is the state before the first connection; the caller starts in it.
export type SseStatus = "connecting" | "connected" | "reconnecting";

export interface SseClientOptions {
  path: string;
  // Only frames with this `event:` name are delivered; everything else is ignored.
  eventName: string;
  // Receives the parsed JSON `data:` of each matching frame. Frames with invalid JSON are skipped.
  onEvent: (data: unknown) => void;
  onStatus: (status: SseStatus) => void;
  // Called every time a connection opens after the first attempt. Events published while the
  // client was offline may be missing (or older than the server's replay buffer), so the caller
  // should refetch its data here.
  onReconnect?: () => void;
}

// failures = consecutive failed attempts so far: 0 -> 1s, 1 -> 2s, 2 -> 4s ... never more than 30s.
export function backoffDelay(failures: number): number {
  return Math.min(MAX_BACKOFF_MS, INITIAL_BACKOFF_MS * 2 ** failures);
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal.addEventListener("abort", finish, { once: true });
  });
}

// Starts the client and returns the function that stops it.
export function connectSse(options: SseClientOptions): () => void {
  const controller = new AbortController();
  void run(options, controller.signal);
  return () => controller.abort();
}

async function run(options: SseClientOptions, signal: AbortSignal): Promise<void> {
  const { path, eventName, onEvent, onStatus, onReconnect } = options;
  let lastEventId: string | null = null;
  let failures = 0;
  let attempts = 0;

  while (!signal.aborted) {
    const isReconnect = attempts > 0;
    attempts += 1;

    // One controller per connection: the stall watchdog can cut a dead connection
    // without stopping the whole client.
    const connection = new AbortController();
    const abortConnection = () => connection.abort();
    signal.addEventListener("abort", abortConnection, { once: true });
    let stallTimer: ReturnType<typeof setTimeout> | undefined;
    const armStallTimer = () => {
      clearTimeout(stallTimer);
      stallTimer = setTimeout(abortConnection, STALL_TIMEOUT_MS);
    };

    try {
      const token = getToken();
      const res: Response = await fetch(`${API_URL}${path}`, {
        headers: {
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(lastEventId !== null ? { "Last-Event-ID": lastEventId } : {}),
        },
        cache: "no-store",
        signal: connection.signal,
      });

      if (res.status === 401) {
        clearToken();
        window.location.assign("/login");
        return;
      }
      if (!res.ok || !res.body) throw new Error(`Event stream unavailable (${res.status})`);

      failures = 0;
      onStatus("connected");
      if (isReconnect) onReconnect?.();
      armStallTimer();

      const reader: ReadableStreamDefaultReader<Uint8Array> = res.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();
      for (;;) {
        const { done, value }: ReadableStreamReadResult<Uint8Array> = await reader.read();
        if (done) break;
        armStallTimer();
        for (const frame of parser.feed(decoder.decode(value, { stream: true }))) {
          if (frame.id !== null) lastEventId = frame.id;
          if (frame.event !== eventName) continue;
          let data: unknown;
          try {
            data = JSON.parse(frame.data);
          } catch {
            continue;
          }
          try {
            onEvent(data);
          } catch (err) {
            // A bug in the handler must not drop the connection.
            console.error("SSE event handler failed", err);
          }
        }
      }
    } catch {
      // Network error, server error, stall watchdog or stop(): decided below.
    } finally {
      clearTimeout(stallTimer);
      signal.removeEventListener("abort", abortConnection);
    }

    if (signal.aborted) return;
    onStatus("reconnecting");
    await sleep(backoffDelay(failures), signal);
    failures += 1;
  }
}
