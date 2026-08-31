"use client";

import { useState } from "react";
import { Supplier, SupplierStatus } from "../types/supplier";
import { STATUS_LABELS, STATUS_OPTIONS } from "../lib/labels";
import { patchRate, patchStatus } from "../services/suppliers";
import { ApiError } from "../lib/api";

interface Props {
  suppliers: Supplier[];
  onUpdated: (updated: Supplier) => void;
}

export default function SupplierTable({ suppliers, onUpdated }: Props) {
  const [savingById, setSavingById] = useState<Record<number, boolean>>({});
  const [errorById, setErrorById] = useState<Record<number, string | null>>({});
  const [editingRateId, setEditingRateId] = useState<number | null>(null);
  const [rateDraft, setRateDraft] = useState("");

  async function handleRateSave(id: number) {
    const value = Number(rateDraft);
    if (!value || value <= 0) {
      setErrorById((prev) => ({ ...prev, [id]: "Rate must be positive." }));
      return;
    }
    setSavingById((prev) => ({ ...prev, [id]: true }));
    setErrorById((prev) => ({ ...prev, [id]: null }));
    try {
      const updated = await patchRate(id, value);
      onUpdated(updated);
      setEditingRateId(null);
    } catch (err) {
      setErrorById((prev) => ({
        ...prev,
        [id]: err instanceof ApiError ? err.message : "Failed to update rate.",
      }));
    } finally {
      setSavingById((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function handleStatusChange(id: number, status: SupplierStatus) {
    setSavingById((prev) => ({ ...prev, [id]: true }));
    setErrorById((prev) => ({ ...prev, [id]: null }));
    try {
      const updated = await patchStatus(id, status);
      onUpdated(updated);
    } catch (err) {
      setErrorById((prev) => ({
        ...prev,
        [id]: err instanceof ApiError ? err.message : "Failed to update status.",
      }));
    } finally {
      setSavingById((prev) => ({ ...prev, [id]: false }));
    }
  }

  if (suppliers.length === 0) {
    return <p className="text-[#5f5a54]">No suppliers found.</p>;
  }

  return (
    <table className="w-full overflow-hidden rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white shadow-[0_14px_30px_rgba(16,16,16,0.05)]">
      <thead className="bg-[#faf3ee] text-left text-sm text-[#5f5a54]">
        <tr>
          <th className="px-4 py-3">Name</th>
          <th className="px-4 py-3">Country</th>
          <th className="px-4 py-3">Categories</th>
          <th className="px-4 py-3">Rate</th>
          <th className="px-4 py-3">Status</th>
          <th className="px-4 py-3">Updated</th>
        </tr>
      </thead>
      <tbody>
        {suppliers.map((s) => {
          const saving = !!savingById[s.id];
          const rowError = errorById[s.id];
          return (
            <tr key={s.id} className="border-t border-[rgba(16,16,16,0.06)] align-top text-sm">
              <td className="px-4 py-3 font-semibold">{s.name}</td>
              <td className="px-4 py-3">{s.country}</td>
              <td className="px-4 py-3">{s.categories.join(", ")}</td>
              <td className="px-4 py-3">
                {editingRateId === s.id ? (
                  <div className="flex gap-1">
                    <input
                      type="number"
                      step="0.01"
                      value={rateDraft}
                      onChange={(e) => setRateDraft(e.target.value)}
                      className="w-24 rounded-lg border border-[rgba(16,16,16,0.14)] px-2 py-1 outline-none focus:border-[#ff6a3d]"
                      disabled={saving}
                    />
                    <button onClick={() => handleRateSave(s.id)} disabled={saving} className="text-xs font-semibold text-[#ff6a3d]">
                      Save
                    </button>
                    <button onClick={() => setEditingRateId(null)} disabled={saving} className="text-xs text-[#5f5a54]">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => {
                      setEditingRateId(s.id);
                      setRateDraft(String(s.rate));
                    }}
                    className="hover:text-[#ff6a3d] hover:underline"
                  >
                    ${s.rate.toFixed(2)}
                  </button>
                )}
              </td>
              <td className="px-4 py-3">
                <select
                  value={s.status}
                  disabled={saving}
                  onChange={(e) => handleStatusChange(s.id, e.target.value as SupplierStatus)}
                  className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                    s.status === "active"
                      ? "border-[#ff6a3d]/30 bg-[#fff1ea] text-[#ff6a3d]"
                      : "border-[rgba(16,16,16,0.14)] bg-[#f2f1ef] text-[#5f5a54]"
                  }`}
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {STATUS_LABELS[opt]}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-4 py-3 text-xs text-[#5f5a54]">
                {new Date(s.updated_at).toLocaleString()}
              </td>
              {rowError && <td className="px-4 text-xs font-semibold text-[#b3261e]">{rowError}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}