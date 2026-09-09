export type ReportingCountry = "US" | "UK";
export type ReportingCurrency = "USD" | "GBP";

// Mirrors one row of reporting_monthly_clinic_supply_performance
// (services/api/main.py GET /reporting/monthly-clinic-supply-performance),
// which returns a flat array of rows - NOT the { month_start, clinics }
// envelope shown as an "indicative example" in CONTEXT section 6.
export interface ClinicSupplyPerformanceRow {
  clinic_id: string;
  month_start: string; // ISO date, e.g. "2026-07-01"
  country: ReportingCountry;
  currency: ReportingCurrency;
  total_supply_cost: number; // KPI: Supply Cost per Clinic
  supply_consumption_count: number; // KPI: Supply Consumption Volume
  critical_stockout_count: number; // KPI: Critical Stockout Frequency
  expiry_risk_count: number; // KPI: Expiry Risk Count
  computed_at: string; // ISO datetime
}

export type PipelineRunStatus = "running" | "success" | "partial" | "failed";

// Mirrors GET /reporting/pipeline-runs/latest response.
export interface PipelineRun {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  month_processed: string[];
  clinics_loaded: number;
  rows_extracted: number;
  status: PipelineRunStatus;
  error_summary: string | null;
  pipeline_version: string;
}

// Mirrors POST /reporting/pipeline-runs response.
export interface TriggerPipelineRunResponse {
  message: string;
  flow_run_id: string;
}