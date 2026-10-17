"use client";

import type { RfpStatus, RfpTicket } from "@/types/rfp";

export const STATUS_LABELS: Record<RfpStatus, string> = {
  analyzing: "Analyzing",
  intake_complete: "Intake complete",
  discarded: "Discarded",
  drafting: "Drafting",
  under_evaluation: "Under evaluation",
  needs_human_review: "Needs human review",
  waiting_for_approval: "Waiting for approval",
  done: "Done",
};

export const STATUS_STYLES: Record<RfpStatus, string> = {
  analyzing: "bg-yellow-100 text-yellow-800",
  intake_complete: "bg-green-100 text-green-800",
  discarded: "bg-red-100 text-red-800",
  drafting: "bg-yellow-100 text-yellow-800",
  under_evaluation: "bg-blue-100 text-blue-800",
  needs_human_review: "bg-orange-100 text-orange-800",
  waiting_for_approval: "bg-purple-100 text-purple-800",
  done: "bg-green-200 text-green-900",
};

export function StatusBadge({ status }: { status: RfpStatus }) {
  // Unknown statuses (a newer API) still render instead of an empty badge.
  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-800";
  const label = STATUS_LABELS[status] ?? status;
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>{label}</span>;
}

export default function RfpTicketTable({
  tickets,
  selectedId,
  onSelect,
}: {
  tickets: RfpTicket[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  if (tickets.length === 0) {
    return <p className="text-sm text-gray-500">No RFPs uploaded yet.</p>;
  }

  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-gray-300">
          <th className="py-2">#</th>
          <th>File</th>
          <th>Status</th>
          <th>Compliance</th>
          <th>Uploaded</th>
        </tr>
      </thead>
      <tbody>
        {tickets.map((ticket) => (
          <tr
            key={ticket.id}
            onClick={() => onSelect(ticket.id)}
            className={`cursor-pointer border-b border-gray-200 hover:bg-gray-100 hover:text-gray-900 ${
              ticket.id === selectedId ? "bg-blue-50 text-gray-900" : ""
            }`}
          >
            <td className="py-2">{ticket.id}</td>
            <td>{ticket.original_filename}</td>
            <td>
              <StatusBadge status={ticket.status} />
            </td>
            <td>
              {ticket.contains_phi ? (
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                  PHI review
                </span>
              ) : (
                <span className="text-xs text-gray-500">-</span>
              )}
            </td>
            <td>{new Date(ticket.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
