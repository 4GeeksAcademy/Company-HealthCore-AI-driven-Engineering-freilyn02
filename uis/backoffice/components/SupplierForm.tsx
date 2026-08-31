"use client";

import { useState } from "react";
import { SUPPLIER_CATEGORIES, SupplierCategory, SupplierCountry } from "../types/supplier";
import { createSupplier } from "../services/suppliers";
import { ApiError } from "../lib/api";

interface Props {
  onCreated: () => void;
}

export default function SupplierForm({ onCreated }: Props) {
  const [name, setName] = useState("");
  const [country, setCountry] = useState<SupplierCountry>("US");
  const [categories, setCategories] = useState<SupplierCategory[]>([]);
  const [rate, setRate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleCategory(cat: SupplierCategory) {
    setCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim() || categories.length === 0 || !rate) {
      setError("Name, at least one category, and rate are required.");
      return;
    }

    setSubmitting(true);
    try {
      await createSupplier({
        name: name.trim(),
        country,
        categories,
        rate: Number(rate),
      });
      setName("");
      setCategories([]);
      setRate("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create supplier.");
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-xl border border-[rgba(16,16,16,0.14)] px-4 py-2 outline-none transition focus:border-[#ff6a3d] focus:ring-2 focus:ring-[#ff6a3d]/20";

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-6 max-w-xl rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white p-6 shadow-[0_14px_30px_rgba(16,16,16,0.05)]"
    >
      <h3 className="mb-4 font-[family-name:var(--font-space-grotesk)] text-lg tracking-[-0.03em]">
        Register supplier
      </h3>

      {error && (
        <p className="mb-3 rounded-xl border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-2 text-sm font-semibold text-[#b3261e]">
          {error}
        </p>
      )}

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Country</label>
        <select
          value={country}
          onChange={(e) => setCountry(e.target.value as SupplierCountry)}
          className={inputClass}
        >
          <option value="US">US</option>
          <option value="UK">UK</option>
        </select>
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-sm text-[#5f5a54]">Categories</label>
        <div className="flex flex-wrap gap-3">
          {SUPPLIER_CATEGORIES.map((cat) => (
            <label key={cat} className="flex items-center gap-1.5 text-sm text-[#101010]">
              <input
                type="checkbox"
                checked={categories.includes(cat)}
                onChange={() => toggleCategory(cat)}
                className="accent-[#ff6a3d]"
              />
              {cat}
            </label>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <label className="mb-1 block text-sm text-[#5f5a54]">Rate</label>
        <input
          type="number"
          step="0.01"
          value={rate}
          onChange={(e) => setRate(e.target.value)}
          className={inputClass}
        />
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="rounded-full bg-[#ff6a3d] px-5 py-3 font-extrabold text-white transition hover:-translate-y-0.5 hover:bg-[#e4542c] disabled:opacity-50"
      >
        {submitting ? "Saving..." : "Register supplier"}
      </button>
    </form>
  );
}