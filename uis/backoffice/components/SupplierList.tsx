"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Supplier } from "../types/supplier";
import { getSuppliers } from "../services/suppliers";
import { ApiError } from "../lib/api";
import SupplierFilters from "./SupplierFilters";
import SupplierTable from "./SupplierTable";
import SupplierForm from "./SupplierForm";

export default function SupplierList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const country = searchParams.get("country") ?? "";
  const category = searchParams.get("category") ?? "";

  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const loadSuppliers = useCallback(async () => {
    setLoadingList(true);
    setListError(null);
    try {
      const data = await getSuppliers({ country, category });
      setSuppliers(data);
    } catch (err) {
      setListError(err instanceof ApiError ? err.message : "Failed to load suppliers.");
    } finally {
      setLoadingList(false);
    }
  }, [country, category]);

  useEffect(() => {
    loadSuppliers();
  }, [loadSuppliers]);

  function updateFilter(key: "country" | "category", value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    router.push(`/suppliers?${params.toString()}`);
  }

  function handleUpdated(updated: Supplier) {
    setSuppliers((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
  }

  return (
    <div>
      <h2 className="mb-6 font-[family-name:var(--font-space-grotesk)] text-2xl tracking-[-0.03em]">HealthCore Supplier Directory</h2>

      <SupplierForm onCreated={loadSuppliers} />

      <SupplierFilters
        country={country}
        category={category}
        onCountryChange={(v) => updateFilter("country", v)}
        onCategoryChange={(v) => updateFilter("category", v)}
      />

      {loadingList && <p className="text-gray-500">Loading suppliers...</p>}

      {listError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2 mb-3">
          {listError}
        </p>
      )}

      {!loadingList && !listError && (
        <SupplierTable suppliers={suppliers} onUpdated={handleUpdated} />
      )}
    </div>
  );
}