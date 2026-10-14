"use client";

import type { RfpTicket } from "@/types/rfp";
import { StatusBadge } from "./RfpTicketTable";

export default function RfpTicketDetail({ ticket }: { ticket: RfpTicket }) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-gray-300 p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">
          Ticket #{ticket.id} - {ticket.original_filename}
        </h2>
        <StatusBadge status={ticket.status} />
      </header>

      {ticket.status === "analizando" && (
        <p className="text-sm text-gray-500">Analyzing... this page refreshes automatically.</p>
      )}

      {ticket.status === "descartado" && (
        <div className="rounded bg-red-50 p-3 text-sm text-red-800">
          <p className="font-medium">This document was discarded.</p>
          <p>{ticket.classifier_reason ?? ticket.error_message ?? "No reason recorded."}</p>
          {ticket.error_message && ticket.classifier_reason && (
            <p className="mt-1 text-xs">Error: {ticket.error_message}</p>
          )}
        </div>
      )}

      {ticket.status === "analisis_completo" && ticket.synthesis && (
        <>
          <p className="text-sm">{ticket.synthesis.summary}</p>
          <p className="text-xs text-gray-500">
            Readability: {ticket.synthesis.readability_estimate} - Next step:{" "}
            {ticket.synthesis.routing_next} ({ticket.routing_status})
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
                <p className="mb-2 text-xs text-gray-500">
                  Contact: {dept.contact ?? "Not available"}
                </p>
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
