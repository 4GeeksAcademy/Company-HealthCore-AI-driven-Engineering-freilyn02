"use client";

import {
  INCIDENT_BRANCHES,
  INCIDENT_ORIGINS,
  INCIDENT_STATUSES,
} from "../types/incident";
import { BRANCH_LABELS, ORIGIN_LABELS, STATUS_LABELS } from "../lib/incidentLabels";

interface Props {
  status: string;
  origin: string;
  branch: string;
  onStatusChange: (value: string) => void;
  onOriginChange: (value: string) => void;
  onBranchChange: (value: string) => void;
}

const selectClass =
  "rounded-xl border border-[rgba(16,16,16,0.14)] px-3 py-1.5 outline-none transition focus:border-[#ff6a3d] focus:ring-2 focus:ring-[#ff6a3d]/20";

export default function IncidentFilters({
  status,
  origin,
  branch,
  onStatusChange,
  onOriginChange,
  onBranchChange,
}: Props) {
  return (
    <div className="mb-4 flex flex-wrap gap-4">
      <div>
        <label className="mb-1 block text-sm text-[#5f5a54]">Status</label>
        <select value={status} onChange={(e) => onStatusChange(e.target.value)} className={selectClass}>
          <option value="">All statuses</option>
          {INCIDENT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-sm text-[#5f5a54]">Origin</label>
        <select value={origin} onChange={(e) => onOriginChange(e.target.value)} className={selectClass}>
          <option value="">All origins</option>
          {INCIDENT_ORIGINS.map((o) => (
            <option key={o} value={o}>
              {ORIGIN_LABELS[o]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-sm text-[#5f5a54]">Branch</label>
        <select value={branch} onChange={(e) => onBranchChange(e.target.value)} className={selectClass}>
          <option value="">All branches</option>
          {INCIDENT_BRANCHES.map((b) => (
            <option key={b} value={b}>
              {BRANCH_LABELS[b]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}