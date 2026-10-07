"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ClinicSupplyPerformanceRow, PipelineRun } from "../types/reporting";
import {
  getLatestPipelineRun,
  getMonthlyClinicSupplyPerformance,
  triggerPipelineRun,
} from "../services/reporting";
import { ApiError } from "../lib/api";

// clinic_id is a snake_case slug (e.g. "austin_north") - there is no
// display-name field in reporting_monthly_clinic_supply_performance, so we
// humanize it here rather than hardcode a name lookup on the frontend.
function formatClinicName(clinicId: string): string {
  return clinicId
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount);
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

interface CurrencySectionProps {
  title: string;
  currency: string;
  rows: ClinicSupplyPerformanceRow[];
}

// CONTEXT section 7: "Never mix currencies in a single aggregate row - USD
// (US clinics) and GBP (UK clinics) are reported separately, side by side,
// not summed together." Each currency gets its own table.
function CurrencySection({ title, currency, rows }: CurrencySectionProps) {
  if (rows.length === 0) return null;

  return (
    <div className="mb-8">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
        {title} ({currency})
      </h3>
      <div className="overflow-x-auto rounded-md border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Clinic</th>
              <th className="px-4 py-2 text-right font-medium text-gray-600">
                Supply Cost per Clinic
              </th>
              <th className="px-4 py-2 text-right font-medium text-gray-600">
                Supply Consumption Volume
              </th>
              <th className="px-4 py-2 text-right font-medium text-gray-600">
                Critical Stockout Frequency
              </th>
              <th className="px-4 py-2 text-right font-medium text-gray-600">
                Expiry Risk Count
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row) => (
              <tr key={row.clinic_id}>
                <td className="px-4 py-2 font-medium text-gray-900">
                  {formatClinicName(row.clinic_id)}
                </td>
                <td className="px-4 py-2 text-right">
                  {formatCurrency(row.total_supply_cost, row.currency)}
                </td>
                <td className="px-4 py-2 text-right">{row.supply_consumption_count}</td>
                <td
                  className={`px-4 py-2 text-right ${
                    row.critical_stockout_count > 0 ? "font-semibold text-red-600" : ""
                  }`}
                >
                  {row.critical_stockout_count}
                </td>
                <td
                  className={`px-4 py-2 text-right ${
                    row.expiry_risk_count > 0 ? "font-semibold text-amber-600" : ""
                  }`}
                >
                  {row.expiry_risk_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ReportingDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Stored in the URL as a full month_start date ("2026-07-01") so it can
  // be passed straight through to the API; the <input type="month"> control
  // only shows/edits the "YYYY-MM" portion.
  const monthStart = searchParams.get("month") ?? "";
  const monthInputValue = monthStart ? monthStart.slice(0, 7) : "";

  const [rows, setRows] = useState<ClinicSupplyPerformanceRow[]>([]);
  const [latestRun, setLatestRun] = useState<PipelineRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, run] = await Promise.all([
        getMonthlyClinicSupplyPerformance(monthStart || undefined),
        getLatestPipelineRun().catch(() => null),
      ]);
      setRows(data);
      setLatestRun(run);
    } catch (err) {
      // 404 means "no data for this month yet" - not a real error state,
      // just show the empty-state message below.
      if (err instanceof ApiError && err.status === 404) {
        setRows([]);
      } else {
        setError(err instanceof ApiError ? err.message : "Failed to load reporting data.");
      }
    } finally {
      setLoading(false);
    }
  }, [monthStart]);

  useEffect(() => {
    load();
  }, [load]);

  function updateMonth(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set("month", `${value}-01`);
    else params.delete("month");
    router.push(`/reporting?${params.toString()}`);
  }

  async function handleRunPipeline() {
    setTriggering(true);
    setError(null);
    try {
      await triggerPipelineRun();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to trigger pipeline run.");
    } finally {
      setTriggering(false);
    }
  }

  const usRows = rows.filter((row) => row.country === "US");
  const ukRows = rows.filter((row) => row.country === "UK");
  const period = rows[0]?.month_start ?? monthStart;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-[family-name:var(--font-space-grotesk)] text-2xl tracking-[-0.03em]">
            Monthly Clinic Supply Performance
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {period
              ? `Period: ${period}`
              : "Board-ready supply cost and risk rollup across all clinics"}
          </p>
        </div>

        <div className="flex items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500" htmlFor="month-filter">
              Month
            </label>
            <input
              id="month-filter"
              type="month"
              value={monthInputValue}
              onChange={(e) => updateMonth(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
            />
          </div>
          <button
            onClick={handleRunPipeline}
            disabled={triggering}
            className="rounded-md bg-gray-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {triggering ? "Running..." : "Run Pipeline"}
          </button>
        </div>
      </div>

      {latestRun && (
        <p className="mb-4 text-xs text-gray-500">
          Last pipeline run:{" "}
          <span
            className={
              latestRun.status === "success"
                ? "font-medium text-green-600"
                : latestRun.status === "failed"
                ? "font-medium text-red-600"
                : "font-medium text-amber-600"
            }
          >
            {latestRun.status}
          </span>{" "}
          ({formatDate(latestRun.finished_at)}) — {latestRun.clinics_loaded} clinics loaded
        </p>
      )}

      {loading && <p className="text-gray-500">Loading reporting data...</p>}

      {error && (
        <p className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      {!loading && !error && rows.length === 0 && (
        <p className="text-gray-500">No reporting data found for the requested month.</p>
      )}

      {!loading && !error && rows.length > 0 && (
        <>
          <CurrencySection title="United States" currency="USD" rows={usRows} />
          <CurrencySection title="United Kingdom" currency="GBP" rows={ukRows} />
        </>
      )}
    </div>
  );
}