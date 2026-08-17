"use client";

import { useCallback, useEffect, useState } from "react";
import { IncidentSummary } from "../types/incident";
import { CATEGORY_LABELS, STATUS_LABELS, BRANCH_LABELS } from "../lib/incidentLabels";
import { getIncidentSummary } from "../services/incidents";
import { ApiError } from "../lib/api";

const cardClass =
  "rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white p-5 shadow-[0_14px_30px_rgba(16,16,16,0.05)]";

function CountList({ title, counts, labels }: { title: string; counts: Record<string, number>; labels: Record<string, string> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div className={cardClass}>
      <h4 className="mb-3 text-sm font-semibold text-[#5f5a54]">{title}</h4>
      {entries.length === 0 ? (
        <p className="text-sm text-[#5f5a54]">No data yet.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {entries.map(([key, count]) => (
            <li key={key} className="flex items-center justify-between">
              <span>{labels[key] ?? key}</span>
              <span className="font-semibold text-[#ff6a3d]">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function IncidentSummaryPanel() {
  const [summary, setSummary] = useState<IncidentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  const fetchSummary = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getIncidentSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load summary.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const cancel = fetchSummary();
    return cancel;
    // retryKey is intentionally in the deps — it exists only to let the
    // Retry button re-trigger this effect on demand.
  }, [fetchSummary, retryKey]);

  // This panel's own failure/loading state never blocks the rest of the page.
  if (loading) {
    return <p className="text-[#5f5a54]">Loading summary...</p>;
  }

  if (error || !summary) {
    return (
      <div className="rounded-xl border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-2 text-sm font-semibold text-[#b3261e]">
        <p className="mb-2">{error ?? "Summary unavailable."}</p>
        <button
          onClick={() => setRetryKey((k) => k + 1)}
          className="rounded-full border border-[#b3261e]/40 bg-white px-3 py-1 text-xs font-semibold text-[#b3261e] transition hover:bg-[#b3261e]/10"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
      <CountList title="By status" counts={summary.by_status} labels={STATUS_LABELS} />
      <CountList title="By category" counts={summary.by_category} labels={CATEGORY_LABELS} />
      <CountList title="By branch" counts={summary.by_branch} labels={BRANCH_LABELS} />
    </div>
  );
}