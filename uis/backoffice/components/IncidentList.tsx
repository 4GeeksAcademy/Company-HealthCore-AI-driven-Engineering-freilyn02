"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Incident, IncidentStatus } from "../types/incident";
import { listIncidents } from "../services/incidents";
import { ApiError } from "../lib/api";
import IncidentForm from "./IncidentForm";
import IncidentFilters from "./IncidentFilters";
import IncidentTable from "./IncidentTable";
import IncidentSummaryPanel from "./IncidentSummaryPanel";

export default function IncidentList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const status = searchParams.get("status") ?? "";
  const origin = searchParams.get("origin") ?? "";
  const branch = searchParams.get("branch") ?? "";

  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const loadIncidents = useCallback(async () => {
    setLoadingList(true);
    setListError(null);
    try {
      const data = await listIncidents({
        status: (status || undefined) as IncidentStatus | undefined,
        origin: origin || undefined,
        branch: branch || undefined,
      });
      setIncidents(data);
    } catch (err) {
      setListError(err instanceof ApiError ? err.message : "Failed to load incidents.");
    } finally {
      setLoadingList(false);
    }
  }, [status, origin, branch]);

  useEffect(() => {
    loadIncidents();
  }, [loadIncidents]);

  function updateFilter(key: "status" | "origin" | "branch", value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    router.push(`/incidents?${params.toString()}`);
  }

  function handleUpdated(updated: Incident) {
    setIncidents((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
  }

  return (
    <div>
      <h2 className="mb-6 font-[family-name:var(--font-space-grotesk)] text-2xl tracking-[-0.03em]">
        HealthCore Centralized Incident Manager
      </h2>

      <IncidentSummaryPanel />

      <IncidentForm onCreated={loadIncidents} />

      <IncidentFilters
        status={status}
        origin={origin}
        branch={branch}
        onStatusChange={(v) => updateFilter("status", v)}
        onOriginChange={(v) => updateFilter("origin", v)}
        onBranchChange={(v) => updateFilter("branch", v)}
      />

      <IncidentTable
        incidents={incidents}
        loading={loadingList}
        error={listError}
        onUpdated={handleUpdated}
        onRetry={loadIncidents}
      />
    </div>
  );
}