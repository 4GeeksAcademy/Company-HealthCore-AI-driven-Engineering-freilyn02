"use client";

import { useEffect } from "react";
import { StatusBadge } from "@/components/RfpTicketTable";
import type { RfpTicketCreatedEvent } from "@/types/rfp";

const AUTO_DISMISS_MS = 15_000;

function Toast({
  notification,
  onView,
  onDismiss,
}: {
  notification: RfpTicketCreatedEvent;
  onView: (ticketId: number) => void;
  onDismiss: (ticketId: number) => void;
}) {
  const { id } = notification;

  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div
      data-testid="rfp-new-ticket-toast"
      className="flex items-start gap-3 rounded-lg border-l-4 border-orange-500 bg-white p-4 text-gray-900 shadow-xl ring-1 ring-orange-200"
    >
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-orange-500 text-white"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5m6 0a3 3 0 1 1-6 0" />
        </svg>
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-extrabold uppercase tracking-wider text-orange-600">New RFP ticket</p>
        <p className="mt-0.5 truncate text-sm font-semibold" title={notification.original_filename}>
          #{id} &middot; {notification.original_filename}
        </p>
        <p className="mt-1 flex items-center gap-2 text-xs text-gray-600">
          <StatusBadge status={notification.status} />
          <span className="font-medium text-orange-700">Needs processing</span>
        </p>
        <button
          type="button"
          onClick={() => onView(id)}
          className="mt-2 rounded bg-orange-500 px-3 py-1 text-xs font-medium text-white hover:bg-orange-600"
        >
          View ticket
        </button>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(id)}
        aria-label={`Dismiss notification for RFP ticket ${id}`}
        className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M18 6 6 18" />
        </svg>
      </button>
    </div>
  );
}

export default function RfpNewTicketToasts({
  notifications,
  onView,
  onDismiss,
}: {
  notifications: RfpTicketCreatedEvent[];
  onView: (ticketId: number) => void;
  onDismiss: (ticketId: number) => void;
}) {
  if (notifications.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="New RFP ticket notifications"
      aria-live="polite"
      className="fixed right-4 top-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-3"
    >
      {notifications.map((notification) => (
        <Toast key={notification.id} notification={notification} onView={onView} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
