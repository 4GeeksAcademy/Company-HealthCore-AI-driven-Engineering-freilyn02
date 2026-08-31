"use client";

import { useState } from "react";
import { Incident, IncidentStatus, VALID_STATUS_TRANSITIONS } from "../types/incident";
import { BRANCH_LABELS, CATEGORY_LABELS, ORIGIN_LABELS, STATUS_LABELS } from "../lib/incidentLabels";
import { updateIncidentStatus } from "../services/incidents";
import { ApiError } from "../lib/api";

interface Props {
  incidents: Incident[];
  loading: boolean;
  error: string | null;
  onUpdated: (updated: Incident) => void;
  onRetry: () => void;
}

const STATUS_BADGE_CLASS: Record<IncidentStatus, string> = {
  open: "border-[#ff6a3d]/30 bg-[#fff1ea] text-[#ff6a3d]",
  in_progress: "border-[#c98a00]/30 bg-[#fff7e6] text-[#c98a00]",
  resolved: "border-[#1b7a3d]/30 bg-[#eefaf1] text-[#1b7a3d]",
  discarded: "border-[rgba(16,16,16,0.14)] bg-[#f2f1ef] text-[#5f5a54]",
};

const FALLBACK_BADGE_CLASS = "border-[rgba(16,16,16,0.14)] bg-[#f2f1ef] text-[#5f5a54]";

export default function IncidentTable({ incidents, loading, error, onUpdated, onRetry }: Props) {
  const [savingById, setSavingById] = useState<Record<string, boolean>>({});
  const [errorById, setErrorById] = useState<Record<string, string | null>>({});

  async function handleStatusChange(id: string, status: IncidentStatus) {
    setSavingById((prev) => ({ ...prev, [id]: true }));
    setErrorById((prev) => ({ ...prev, [id]: null }));
    try {
      const updated = await updateIncidentStatus(id, status);
      onUpdated(updated);
    } catch (err) {
      // The <select> is controlled by the incident prop, which we did NOT
      // change on failure — so it reverts to the current status automatically.
      setErrorById((prev) => ({
        ...prev,
        [id]: err instanceof ApiError ? err.message : "Failed to update status.",
      }));
    } finally {
      setSavingById((prev) => ({ ...prev, [id]: false }));
    }
  }

  if (loading) {
    return <p className="text-[#5f5a54]">Loading incidents...</p>;
  }

  if (error) {
    return (
      <div className="rounded-xl border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-2 text-sm font-semibold text-[#b3261e]">
        <p className="mb-2">{error}</p>
        <button
          onClick={onRetry}
          className="rounded-full border border-[#b3261e]/40 bg-white px-3 py-1 text-xs font-semibold text-[#b3261e] transition hover:bg-[#b3261e]/10"
        >
          Retry
        </button>
      </div>
    );
  }

  if (incidents.length === 0) {
    return <p className="text-[#5f5a54]">No incidents found.</p>;
  }

  return (
    <table className="w-full overflow-hidden rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white shadow-[0_14px_30px_rgba(16,16,16,0.05)]">
      <thead className="bg-[#faf3ee] text-left text-sm text-[#5f5a54]">
        <tr>
          <th className="px-4 py-3">Title</th>
          <th className="px-4 py-3">Category</th>
          <th className="px-4 py-3">Origin</th>
          <th className="px-4 py-3">Branch</th>
          <th className="px-4 py-3">Status</th>
          <th className="px-4 py-3">Updated</th>
        </tr>
      </thead>
      <tbody>
        {incidents.map((inc) => {
          const saving = !!savingById[inc.id];
          const rowError = errorById[inc.id];
          const nextOptions = VALID_STATUS_TRANSITIONS[inc.status] ?? [];
          const isFinal = nextOptions.length === 0;

          return (
            <tr key={inc.id} className="border-t border-[rgba(16,16,16,0.06)] align-top text-sm">
              <td className="px-4 py-3 font-semibold">{inc.title}</td>
              <td className="px-4 py-3">{CATEGORY_LABELS[inc.category] ?? "Unknown"}</td>
              <td className="px-4 py-3">{ORIGIN_LABELS[inc.origin] ?? "Unknown"}</td>
              <td className="px-4 py-3">{BRANCH_LABELS[inc.branch] ?? "Unknown"}</td>
              <td className="px-4 py-3">
                <select
                  value={inc.status}
                  disabled={saving || isFinal}
                  onChange={(e) => handleStatusChange(inc.id, e.target.value as IncidentStatus)}
                  className={`rounded-full border px-3 py-1 text-xs font-semibold disabled:opacity-70 ${
                    STATUS_BADGE_CLASS[inc.status] ?? FALLBACK_BADGE_CLASS
                  }`}
                >
                  <option value={inc.status}>{STATUS_LABELS[inc.status] ?? inc.status}</option>
                  {nextOptions.map((s) => (
                    <option key={s} value={s}>
                      {STATUS_LABELS[s]}
                    </option>
                  ))}
                </select>
                {rowError && (
                  <p className="mt-1 text-xs font-semibold text-[#b3261e]">{rowError}</p>
                )}
              </td>
              <td className="px-4 py-3 text-xs text-[#5f5a54]">
                {new Date(inc.updated_at).toLocaleString()}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}