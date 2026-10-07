"use client";

import { useEffect } from "react";
import { initTelemetry, track } from "@/services/telemetry";

// Strips anything that looks like it could carry user-entered data (form
// values interpolated into an error message) — keeps only the error's own
// wording, never the specifics of what was being processed.
function sanitizeErrorMessage(message: string): string {
  return message.slice(0, 200);
}

// Mounts once at the root of the app: wires up the flush timer, the
// sendBeacon listener, and a global capture for uncaught errors/rejections
// (the "errors" leg of the technical baseline required alongside business
// events — see docs/telemetry/telemetry-plan.md Phase 3).
export default function TelemetryInit() {
  useEffect(() => {
    initTelemetry();

    function handleError(event: ErrorEvent) {
      track("frontend_error_caught", {
        page: window.location.pathname,
        error_type: event.error?.name ?? "Error",
        error_message: sanitizeErrorMessage(event.message ?? "Unknown error"),
      });
    }

    function handleRejection(event: PromiseRejectionEvent) {
      const reason = event.reason;
      track("frontend_error_caught", {
        page: window.location.pathname,
        error_type: "UnhandledRejection",
        error_message: sanitizeErrorMessage(
          reason instanceof Error ? reason.message : String(reason)
        ),
      });
    }

    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);

    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  return null;
}