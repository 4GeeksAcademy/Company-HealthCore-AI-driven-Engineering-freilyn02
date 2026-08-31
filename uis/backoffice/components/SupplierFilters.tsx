"use client";

import { SUPPLIER_CATEGORIES, SupplierCountry } from "../types/supplier";

interface Props {
  country: string;
  category: string;
  onCountryChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
}

const COUNTRIES: SupplierCountry[] = ["US", "UK"];
const selectClass =
  "rounded-xl border border-[rgba(16,16,16,0.14)] px-3 py-1.5 outline-none transition focus:border-[#ff6a3d] focus:ring-2 focus:ring-[#ff6a3d]/20";

export default function SupplierFilters({
  country,
  category,
  onCountryChange,
  onCategoryChange,
}: Props) {
  return (
    <div className="mb-4 flex gap-4">
      <div>
        <label className="mb-1 block text-sm text-[#5f5a54]">Country</label>
        <select value={country} onChange={(e) => onCountryChange(e.target.value)} className={selectClass}>
          <option value="">All countries</option>
          {COUNTRIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-sm text-[#5f5a54]">Category</label>
        <select value={category} onChange={(e) => onCategoryChange(e.target.value)} className={selectClass}>
          <option value="">All categories</option>
          {SUPPLIER_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}