"use client";

import { useCallback, useEffect, useState } from "react";
import RfpTicketDetail from "@/components/RfpTicketDetail";
import RfpTicketTable from "@/components/RfpTicketTable";
import RfpUploadForm from "@/components/RfpUploadForm";
import { getRfpTicket, listRfpTickets } from "@/lib/rfp";
import type { RfpTicket } from "@/types/rfp";

const POLL_INTERVAL_MS = 3000;
// Statuses that change on their own (background pipelines): keep polling while any ticket has one.
const ACTIVE_STATUSES = ["analyzing", "drafting"];

export default function RfpPage() {
  const [tickets, setTickets] = useState<RfpTicket[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<RfpTicket | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setTickets(await listRfpTickets());
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
        setTickets(list);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load tickets.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Poll only while at least one ticket is still being processed in the background.
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
    setSelectedId(ticketId);
    void refresh();
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <h1 className="text-2xl font-bold">RFP Intake</h1>
      <RfpUploadForm onUploaded={handleUploaded} />
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      <RfpTicketTable tickets={tickets} selectedId={selectedId} onSelect={setSelectedId} />
      {selected && selected.id === selectedId && <RfpTicketDetail ticket={selected} onChanged={refresh} />}
    </main>
  );
}
