"use client";

import { useState } from "react";
import {
  IncidentBranch,
  IncidentCategory,
  IncidentOrigin,
  INCIDENT_BRANCHES,
  INCIDENT_CATEGORIES,
  INCIDENT_ORIGINS,
} from "../types/incident";
import { BRANCH_LABELS, CATEGORY_LABELS, ORIGIN_LABELS } from "../lib/incidentLabels";
import { createIncident } from "../services/incidents";
import { ApiError } from "../lib/api";

interface Props {
  onCreated: () => void;
}

interface FieldErrors {
  title?: string;
  description?: string;
  category?: string;
  origin?: string;
  branch?: string;
  form?: string;
}

export default function IncidentForm({ onCreated }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<IncidentCategory>("other");
  const [origin, setOrigin] = useState<IncidentOrigin>("customer");
  const [branch, setBranch] = useState<IncidentBranch>("central");
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [success, setSuccess] = useState(false);

  const inputClass =
    "w-full rounded-xl border border-[rgba(16,16,16,0.14)] px-4 py-2 outline-none transition focus:border-[#ff6a3d] focus:ring-2 focus:ring-[#ff6a3d]/20";

  const errorInputClass =
    "w-full rounded-xl border border-[#b3261e] px-4 py-2 outline-none transition focus:border-[#b3261e] focus:ring-2 focus:ring-[#b3261e]/20";

  function resetForm() {
    setTitle("");
    setDescription("");
    setCategory("other");
    setOrigin("customer");
    setBranch("central");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setSuccess(false);

    const nextErrors: FieldErrors = {};
    if (!title.trim()) nextErrors.title = "Title is required.";
    if (!description.trim()) nextErrors.description = "Description is required.";
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }

    setSubmitting(true);
    try {
      await createIncident({
        title: title.trim(),
        description: description.trim(),
        category,
        origin,
        branch,
      });
      resetForm();
      setSuccess(true);
      onCreated();
    } catch (err) {
      if (err instanceof ApiError && err.field) {
        setErrors({ [err.field]: err.message } as FieldErrors);
      } else {
        setErrors({
          form: err instanceof ApiError ? err.message : "Failed to create incident.",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-6 max-w-xl rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white p-6 shadow-[0_14px_30px_rgba(16,16,16,0.05)]"
    >
      <h3 className="mb-4 font-[family-name:var(--font-space-grotesk)] text-lg tracking-[-0.03em]">
        Report incident
      </h3>

      {errors.form && (
        <p className="mb-3 rounded-xl border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-2 text-sm font-semibold text-[#b3261e]">
          {errors.form}
        </p>
      )}

      {success && (
        <p className="mb-3 rounded-xl border border-[#1b7a3d]/20 bg-[#1b7a3d]/5 px-3 py-2 text-sm font-semibold text-[#1b7a3d]">
          Incident reported successfully.
        </p>
      )}

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Title</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className={errors.title ? errorInputClass : inputClass}
        />
        {errors.title && <p className="mt-1 text-xs text-[#b3261e]">{errors.title}</p>}
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Description</label>
        {/* Mandatory patient-data warning — regulatory requirement, must stay visible and prominent, not small gray text */}
        <p className="mb-1.5 rounded-lg border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-1.5 text-xs font-semibold text-[#b3261e]">
          ⚠ Do not enter any patient-identifying information (name, date of birth, medical
          record number, or contact details) in this field.
        </p>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={4}
          className={errors.description ? errorInputClass : inputClass}
        />
        {errors.description && (
          <p className="mt-1 text-xs text-[#b3261e]">{errors.description}</p>
        )}
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Category</label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as IncidentCategory)}
          className={errors.category ? errorInputClass : inputClass}
        >
          {INCIDENT_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>
              {CATEGORY_LABELS[cat]}
            </option>
          ))}
        </select>
        {errors.category && <p className="mt-1 text-xs text-[#b3261e]">{errors.category}</p>}
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Origin</label>
        <select
          value={origin}
          onChange={(e) => setOrigin(e.target.value as IncidentOrigin)}
          className={errors.origin ? errorInputClass : inputClass}
        >
          {INCIDENT_ORIGINS.map((o) => (
            <option key={o} value={o}>
              {ORIGIN_LABELS[o]}
            </option>
          ))}
        </select>
        {errors.origin && <p className="mt-1 text-xs text-[#b3261e]">{errors.origin}</p>}
      </div>

      {/* Branch is always visible/required, but visually highlighted when origin=branch */}
      <div
        className={
          origin === "branch"
            ? "mb-4 rounded-xl border-2 border-[#ff6a3d] bg-[#ff6a3d]/5 p-3"
            : "mb-4"
        }
      >
        <label className="mb-1 block text-sm text-[#5f5a54]">
          Branch
          {origin === "branch" && (
            <span className="ml-2 text-xs font-semibold text-[#ff6a3d]">
              — required for branch-reported incidents
            </span>
          )}
        </label>
        <select
          value={branch}
          onChange={(e) => setBranch(e.target.value as IncidentBranch)}
          className={errors.branch ? errorInputClass : inputClass}
        >
          {INCIDENT_BRANCHES.map((b) => (
            <option key={b} value={b}>
              {BRANCH_LABELS[b]}
            </option>
          ))}
        </select>
        {errors.branch && <p className="mt-1 text-xs text-[#b3261e]">{errors.branch}</p>}
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="rounded-full bg-[#ff6a3d] px-5 py-3 font-extrabold text-white transition hover:-translate-y-0.5 hover:bg-[#e4542c] disabled:opacity-50"
      >
        {submitting ? "Saving..." : "Report incident"}
      </button>
    </form>
  );
}
