"use client";

import type { SseStatus } from "@/lib/sse";

const CONFIG: Record<SseStatus, { label: string; pill: string; dot: string }> = {
  connected: {
    label: "Live updates: connected",
    pill: "bg-green-100 text-green-800",
    dot: "bg-green-500",
  },
  reconnecting: {
    label: "Live updates: reconnecting...",
    pill: "bg-yellow-100 text-yellow-800",
    dot: "animate-pulse bg-yellow-500",
  },
  connecting: {
    label: "Live updates: connecting...",
    pill: "bg-gray-100 text-gray-800",
    dot: "animate-pulse bg-gray-400",
  },
};

export default function RealtimeStatus({ status }: { status: SseStatus }) {
  const { label, pill, dot } = CONFIG[status];
  return (
    <span
      role="status"
      data-status={status}
      className={`inline-flex items-center gap-2 rounded-full px-2 py-0.5 text-xs font-medium ${pill}`}
    >
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
