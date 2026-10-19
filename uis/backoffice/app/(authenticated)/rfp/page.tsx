"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import RealtimeStatus from "@/components/RealtimeStatus";
import RfpNewTicketToasts from "@/components/RfpNewTicketToasts";
import RfpTicketDetail from "@/components/RfpTicketDetail";
import RfpTicketTable from "@/components/RfpTicketTable";
import RfpUploadForm from "@/components/RfpUploadForm";
import { useSse } from "@/lib/useSse";
import {
  RFP_EVENTS_PATH,
  RFP_TICKET_CREATED_EVENT,
  getRfpTicket,
  listRfpTickets,
  mergeRfpTickets,
  parseRfpTicketCreated,
  ticketFromCreatedEvent,
} from "@/lib/rfp";
import type { RfpTicket, RfpTicketCreatedEvent } from "@/types/rfp";

const POLL_INTERVAL_MS = 3000;
// Statuses that change on their own (background pipelines): keep polling while any ticket has one.
const ACTIVE_STATUSES = ["analyzing", "drafting"];
const MAX_TOASTS = 5;

function toNotification(ticket: RfpTicket): RfpTicketCreatedEvent {
  return {
    id: ticket.id,
    status: ticket.status,
    original_filename: ticket.original_filename,
    created_at: ticket.created_at,
  };
}

export default function RfpPage() {
  const [tickets, setTickets] = useState<RfpTicket[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<RfpTicket | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Tickets that arrived in real time and have not been opened yet.
  const [notifications, setNotifications] = useState<RfpTicketCreatedEvent[]>([]);
  const [highlightedIds, setHighlightedIds] = useState<ReadonlySet<number>>(() => new Set());

  // Read by the stream callbacks, which outlive any single render.
  const ticketsRef = useRef<RfpTicket[]>(tickets);
  const loadedRef = useRef(false);
  useEffect(() => {
    ticketsRef.current = tickets;
  });

  // Merging (instead of replacing) means a ticket pushed by the stream while a list request
  // was in flight is never lost, and a ticket never shows up twice.
  const refresh = useCallback(async () => {
    try {
      const list = await listRfpTickets();
      setTickets((current) => mergeRfpTickets(current, list, { preferIncoming: true }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load tickets.");
    }
  }, []);

  // Initial load (plain promise chain: no synchronous setState in the effect body).
  useEffect(() => {
    let cancelled = false;
    listRfpTickets()
      .then((list) => {
        if (cancelled) return;
        setTickets((current) => mergeRfpTickets(current, list, { preferIncoming: true }));
        setError(null);
        loadedRef.current = true;
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load tickets.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const addNotifications = useCallback((incoming: RfpTicketCreatedEvent[]) => {
    if (incoming.length === 0) return;
    setNotifications((current) => {
      const known = new Set(current.map((n) => n.id));
      const fresh = incoming.filter((n) => !known.has(n.id));
      return [...fresh, ...current].slice(0, MAX_TOASTS);
    });
    setHighlightedIds((current) => {
      const next = new Set(current);
      for (const n of incoming) next.add(n.id);
      return next;
    });
  }, []);

  const dismissNotification = useCallback((ticketId: number) => {
    setNotifications((current) => current.filter((n) => n.id !== ticketId));
  }, []);

  // Opening a ticket means it has been seen: drop its toast and its "New" highlight.
  const markSeen = useCallback((ticketId: number) => {
    setNotifications((current) => current.filter((n) => n.id !== ticketId));
    setHighlightedIds((current) => {
      if (!current.has(ticketId)) return current;
      const next = new Set(current);
      next.delete(ticketId);
      return next;
    });
  }, []);

  const handleSelect = useCallback(
    (ticketId: number) => {
      setSelectedId(ticketId);
      markSeen(ticketId);
    },
    [markSeen],
  );

  // A ticket arrived on the stream: add only that ticket (no list refetch), then notify.
  const handleTicketCreated = useCallback(
    (data: unknown) => {
      const event = parseRfpTicketCreated(data);
      if (!event) return;
      // Already in the list (own upload, polling or a replayed event): nothing new to announce.
      if (ticketsRef.current.some((t) => t.id === event.id)) return;
      setTickets((current) => mergeRfpTickets(current, [ticketFromCreatedEvent(event)], { preferIncoming: false }));
      addNotifications([event]);
    },
    [addNotifications],
  );

  // After a reconnect, events published while offline may be gone from the server's replay
  // buffer: refetch the list, merge it, and announce tickets we had not seen yet.
  const handleReconnect = useCallback(() => {
    listRfpTickets()
      .then((list) => {
        if (loadedRef.current) {
          const known = new Set(ticketsRef.current.map((t) => t.id));
          addNotifications(list.filter((t) => !known.has(t.id)).map(toNotification));
        }
        setTickets((current) => mergeRfpTickets(current, list, { preferIncoming: true }));
        setError(null);
      })
      .catch(() => {
        // The stream reconnected but the list request failed: the next poll or reconnect retries.
      });
  }, [addNotifications]);

  const connectionStatus = useSse({
    path: RFP_EVENTS_PATH,
    eventName: RFP_TICKET_CREATED_EVENT,
    onEvent: handleTicketCreated,
    onReconnect: handleReconnect,
  });

  // Poll only while at least one ticket is still being processed in the background.
  // (A ticket that just arrived is `analyzing`, so this also fills in its full data.)
  const hasActive = tickets.some((t) => ACTIVE_STATUSES.includes(t.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasActive, refresh]);

  // Reload the detail whenever the selection or its status changes.
  const selectedStatus = tickets.find((t) => t.id === selectedId)?.status;
  useEffect(() => {
    if (selectedId === null) return;
    let cancelled = false;
    getRfpTicket(selectedId)
      .then((ticket) => {
        if (!cancelled) setSelected(ticket);
      })
      .catch(() => {
        if (!cancelled) setSelected(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedStatus]);

  function handleUploaded(ticketId: number) {
    handleSelect(ticketId);
    void refresh();
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <RfpNewTicketToasts notifications={notifications} onView={handleSelect} onDismiss={dismissNotification} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">RFP Intake</h1>
        <RealtimeStatus status={connectionStatus} />
      </div>
      <RfpUploadForm onUploaded={handleUploaded} />
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <RfpTicketTable
        tickets={tickets}
        selectedId={selectedId}
        onSelect={handleSelect}
        highlightedIds={highlightedIds}
      />
      {selected && selected.id === selectedId && <RfpTicketDetail ticket={selected} onChanged={refresh} />}
    </main>
  );
}
