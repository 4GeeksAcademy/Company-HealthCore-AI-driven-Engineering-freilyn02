import { getToken } from "../lib/auth";

const TELEMETRY_ENDPOINT = process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT;
const TELEMETRY_PATH = "/telemetry/events";
const SCHEMA_VERSION = "1.0.0";
const FLUSH_INTERVAL_MS = 10_000;
const MAX_QUEUE_SIZE = 20;
const MAX_RETRIES = 3;
const RETRY_BASE_DELAY_MS = 500;
const SESSION_ID_KEY = "telemetry_session_id";

interface TelemetryEvent {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string;
  event_type: string;
  schemaVersion: string;
  requestId: string;
  properties: Record<string, unknown>;
}

let queue: TelemetryEvent[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;

// One session id per browser tab session — persists across page navigations,
// resets when the tab closes (sessionStorage, not localStorage).
function getSessionId(): string {
  if (typeof window === "undefined") return "server";
  let sessionId = sessionStorage.getItem(SESSION_ID_KEY);
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem(SESSION_ID_KEY, sessionId);
  }
  return sessionId;
}

// Reads the JWT's "sub" claim (set by the backend as the user id) without
// verifying the signature — this is only a descriptive label for telemetry,
// never used for authorization.
function getUserId(): string {
  const token = getToken();
  if (!token) return "anonymous";
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload));
    return decoded.sub ? String(decoded.sub) : "anonymous";
  } catch {
    return "anonymous";
  }
}

function buildEvent(
  eventType: string,
  properties: Record<string, unknown>
): TelemetryEvent {
  return {
    eventId: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    sessionId: getSessionId(),
    userId: getUserId(),
    event_type: eventType,
    schemaVersion: SCHEMA_VERSION,
    requestId: crypto.randomUUID(),
    properties,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Fire-and-forget by design: telemetry failures are logged, retried, and
// eventually discarded — they must never surface to the user or throw.
async function sendBatch(events: TelemetryEvent[], attempt = 1): Promise<void> {
  if (events.length === 0 || !TELEMETRY_ENDPOINT) return;
  console.log("🟠 sendBatch() attempt", attempt, "endpoint:", TELEMETRY_ENDPOINT);

  try {
    const res = await fetch(`${TELEMETRY_ENDPOINT}${TELEMETRY_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
    console.log("🔵 fetch response status:", res.status);
    if (!res.ok) {
      throw new Error(`Telemetry request failed with status ${res.status}`);
    }
  } catch (error) {
    console.log("🔴 fetch error:", error);
    if (attempt >= MAX_RETRIES) {
      console.error("Telemetry: discarding batch after max retries", error);
      return;
    }
    await sleep(RETRY_BASE_DELAY_MS * 2 ** (attempt - 1));
    await sendBatch(events, attempt + 1);
  }
}

function flush(): void {
  if (queue.length === 0) return;
  console.log("🟡 flush() called, queue length:", queue.length);
  const batch = queue;
  queue = [];
  void sendBatch(batch);
}

// Public API — the only way the rest of the app should send telemetry.
// Callers never pass eventId/sessionId/userId/timestamp/schemaVersion/requestId;
// buildEvent() adds all of those automatically.
export function track(
  eventType: string,
  properties: Record<string, unknown> = {}
): void {
  queue.push(buildEvent(eventType, properties));
  if (queue.length >= MAX_QUEUE_SIZE) {
    flush();
  }
}

// Best-effort delivery when the tab is being hidden/closed. sendBeacon can't
// retry, so if queuing it fails outright we fall back to a normal fetch.
function flushWithBeacon(): void {
  if (
    queue.length === 0 ||
    typeof navigator === "undefined" ||
    !navigator.sendBeacon ||
    !TELEMETRY_ENDPOINT
  ) {
    return;
  }
  const batch = queue;
  queue = [];
  const blob = new Blob([JSON.stringify({ events: batch })], {
    type: "application/json",
  });
  const queued = navigator.sendBeacon(`${TELEMETRY_ENDPOINT}${TELEMETRY_PATH}`, blob);
  if (!queued) {
    void sendBatch(batch);
  }
}

// Call this once, on app startup (e.g. from the root layout's client boundary).
// Safe to call multiple times — only the first call wires up the timer/listener.
export function initTelemetry(): void {
  if (typeof window === "undefined" || flushTimer) return;

  flushTimer = setInterval(flush, FLUSH_INTERVAL_MS);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      flushWithBeacon();
    }
  });
}