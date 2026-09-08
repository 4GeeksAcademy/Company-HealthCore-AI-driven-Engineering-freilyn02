import { apiFetch } from "../lib/api";
import {
  ClinicSupplyPerformanceRow,
  PipelineRun,
  TriggerPipelineRunResponse,
} from "../types/reporting";

// GET /reporting/monthly-clinic-supply-performance?month_start=YYYY-MM-01
// Omitting monthStart lets the API default to the most recently computed
// month (see CONTEXT section 6 and services/api/main.py).
export function getMonthlyClinicSupplyPerformance(
  monthStart?: string
): Promise<ClinicSupplyPerformanceRow[]> {
  const params = new URLSearchParams();
  if (monthStart) params.set("month_start", monthStart);
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<ClinicSupplyPerformanceRow[]>(
    `/reporting/monthly-clinic-supply-performance${query}`
  );
}

// GET /reporting/pipeline-runs/latest
export function getLatestPipelineRun(): Promise<PipelineRun> {
  return apiFetch<PipelineRun>("/reporting/pipeline-runs/latest");
}

// POST /reporting/pipeline-runs
export function triggerPipelineRun(): Promise<TriggerPipelineRunResponse> {
  return apiFetch<TriggerPipelineRunResponse>("/reporting/pipeline-runs", {
    method: "POST",
  });
}