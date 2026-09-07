"use client";

import { useEffect } from "react";
import { initTelemetry } from "@/services/telemetry";

// Mounts once at the root of the app and wires up the flush timer +
// sendBeacon listener. Renders nothing — this is a side-effect-only component.
export default function TelemetryInit() {
  useEffect(() => {
    initTelemetry();
  }, []);

  return null;
}