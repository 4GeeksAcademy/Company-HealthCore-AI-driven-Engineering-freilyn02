"use client";

import { useState } from "react";
import { generateRfpResponse } from "@/lib/rfp";
import type { RfpTicket } from "@/types/rfp";
import RfpApprovalPanel from "./RfpApprovalPanel";
import { StatusBadge } from "./RfpTicketTable";

function MetadataField({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt className="text-xs uppercase text-gray-500">{label}</dt>
      <dd className="text-sm">{value ?? "Not stated"}</dd>
    </div>
  );
}

// Statuses in which Part 1 already produced the synthesis the departments read.
const HAS_SYNTHESIS = [
  "intake_complete",
  "drafting",
  "under_evaluation",
  "needs_human_review",
  "waiting_for_approval",
  "done",
];
// Statuses in which the approval panel is relevant (Part 2 finished or Part 3 running).
const HAS_APPROVALS = ["under_evaluation", "needs_human_review", "waiting_for_approval", "done"];

export default function RfpTicketDetail({
  ticket,
  onChanged,
}: {
  ticket: RfpTicket;
  onChanged: () => void;
}) {
  const meta = ticket.rfp_metadata;
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await generateRfpResponse(ticket.id);
      onChanged();
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Could not start the response generation.");
    } finally {
      setGenerating(false);
    }
  }

  const canGenerate = ticket.status === "intake_complete" && ticket.routing_status === "ready_for_part2";

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-gray-300 p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">
          Ticket #{ticket.id} - {ticket.original_filename}
        </h2>
        <StatusBadge status={ticket.status} />
      </header>

      {ticket.contains_phi && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          <p className="font-medium">Possible patient data detected and redacted.</p>
          <p>
            Compliance human review is required before this RFP moves to the next step. No patient data is
            stored or shown here.
          </p>
          {ticket.phi_findings && (
            <p className="mt-1 text-xs">
              Detected types:{" "}
              {Object.entries(ticket.phi_findings)
                .map(([kind, count]) => `${kind} (${count})`)
                .join(", ")}
            </p>
          )}
        </div>
      )}

      {ticket.status === "analyzing" && (
        <p className="text-sm text-gray-500">Analyzing... this page refreshes automatically.</p>
      )}

      {ticket.status === "drafting" && (
        <p className="text-sm text-gray-500">Drafting the response... this page refreshes automatically.</p>
      )}

      {ticket.status === "discarded" && (
        <div className="rounded bg-red-50 p-3 text-sm text-red-800">
          <p className="font-medium">This document was discarded.</p>
          <p>{ticket.classifier_reason ?? ticket.error_message ?? "No reason recorded."}</p>
          {ticket.error_message && ticket.classifier_reason && (
            <p className="mt-1 text-xs">Error: {ticket.error_message}</p>
          )}
        </div>
      )}

      {canGenerate && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={generating}
            className="w-fit rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {generating ? "Starting..." : "Generate response"}
          </button>
          {generateError && (
            <p role="alert" className="text-sm text-red-600">
              {generateError}
            </p>
          )}
        </div>
      )}

      {HAS_SYNTHESIS.includes(ticket.status) && ticket.synthesis && (
        <>
          <p className="text-sm">{ticket.synthesis.summary}</p>

          {meta && (
            <dl className="grid gap-3 rounded border border-gray-300 p-3 sm:grid-cols-3">
              <MetadataField label="Client" value={meta.client_name} />
              <MetadataField label="Country" value={meta.client_country} />
              <MetadataField label="Program" value={meta.program_type} />
              <MetadataField label="Covered population" value={meta.covered_population} />
              <MetadataField label="Deadline" value={meta.deadline} />
              <MetadataField label="Budget" value={meta.budget_range} />
              <MetadataField label="Quote currency" value={meta.currency} />
            </dl>
          )}

          <p className="text-xs text-gray-500">
            Readability: {ticket.synthesis.readability_estimate} - Next step: {ticket.synthesis.routing_next} (
            {ticket.routing_status})
          </p>

          {ticket.synthesis.unknown_departments.length > 0 && (
            <p className="rounded bg-yellow-50 p-2 text-xs text-yellow-800">
              Departments not in our company context (needs manual review):{" "}
              {ticket.synthesis.unknown_departments.join(", ")}
            </p>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            {ticket.synthesis.by_department.map((dept) => (
              <article key={dept.department} className="rounded border border-gray-300 p-3">
                <h3 className="font-medium">{dept.label}</h3>
                <p className="mb-2 text-xs text-gray-500">Contact: {dept.contact ?? "Not available"}</p>
                {dept.failed && (
                  <p className="mb-2 text-xs text-red-600">Analysis failed for this department.</p>
                )}
                <p className="text-xs font-semibold uppercase text-gray-500">What they need</p>
                <ul className="mb-2 list-disc pl-5 text-sm">
                  {dept.needs.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                {dept.open_questions.length > 0 && (
                  <>
                    <p className="text-xs font-semibold uppercase text-gray-500">Open questions</p>
                    <ul className="list-disc pl-5 text-sm">
                      {dept.open_questions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </>
                )}
              </article>
            ))}
          </div>
        </>
      )}

      {HAS_APPROVALS.includes(ticket.status) && <RfpApprovalPanel key={ticket.id} ticket={ticket} onChanged={onChanged} />}
    </section>
  );
}
