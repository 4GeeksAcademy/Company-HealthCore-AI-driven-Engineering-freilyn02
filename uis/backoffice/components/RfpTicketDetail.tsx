"use client";

import type { RfpTicket } from "@/types/rfp";
import { StatusBadge } from "./RfpTicketTable";

function MetadataField({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt className="text-xs uppercase text-gray-500">{label}</dt>
      <dd className="text-sm">{value ?? "Not stated"}</dd>
    </div>
  );
}

export default function RfpTicketDetail({ ticket }: { ticket: RfpTicket }) {
  const meta = ticket.rfp_metadata;

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

      {ticket.status === "discarded" && (
        <div className="rounded bg-red-50 p-3 text-sm text-red-800">
          <p className="font-medium">This document was discarded.</p>
          <p>{ticket.classifier_reason ?? ticket.error_message ?? "No reason recorded."}</p>
          {ticket.error_message && ticket.classifier_reason && (
            <p className="mt-1 text-xs">Error: {ticket.error_message}</p>
          )}
        </div>
      )}

      {ticket.status === "intake_complete" && ticket.synthesis && (
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
    </section>
  );
}
