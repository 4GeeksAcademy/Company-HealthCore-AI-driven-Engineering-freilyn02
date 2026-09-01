// app/(authenticated)/inventory/orders/outbound/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { listProducts, createOutboundOrder } from "@/lib/inventory";
import { ApiError } from "@/lib/api";
import type { MedicalSupply, ConsumptionType } from "@/types/inventory";

// Clinic IDs range from 1-12 (9 US clinics, 3 UK clinics) per CONTEXT-healthcore.md.
const CLINIC_IDS = Array.from({ length: 12 }, (_, i) => i + 1);

const CONSUMPTION_TYPE_LABELS: Record<ConsumptionType, string> = {
  clinical_use: "Clinical Use",
  expiry_waste: "Expiry / Waste",
};

export default function OutboundOrderPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [products, setProducts] = useState<MedicalSupply[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [supplyId, setSupplyId] = useState<string>(searchParams.get("supply_id") ?? "");
  const [quantity, setQuantity] = useState<string>("");
  const [consumptionType, setConsumptionType] = useState<string>("");
  const [clinicId, setClinicId] = useState<string>("");

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await listProducts();
        setProducts(data);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Failed to load medical supplies.";
        setLoadError(message);
      } finally {
        setLoadingProducts(false);
      }
    }
    load();
  }, []);

  // Reactive stock: derived directly from the already-loaded products list
  // (current_stock updates immediately when the selection changes, per README).
  const selectedProduct = products.find((p) => String(p.id) === supplyId) ?? null;

  // Client-side guard (UX only — the API enforces the real rule).
  const quantityExceedsStock =
    selectedProduct !== null &&
    quantity !== "" &&
    Number(quantity) > selectedProduct.current_stock;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    setSuccess(false);

    if (!supplyId || !quantity || !consumptionType || !clinicId) {
      setSubmitError("Please fill in all fields.");
      return;
    }

    setSubmitting(true);
    try {
      await createOutboundOrder({
        supply_id: Number(supplyId),
        quantity: Number(quantity),
        consumption_type: consumptionType as ConsumptionType,
        clinic_id: Number(clinicId),
      });
      setSuccess(true);
      // Clear the form (README requirement: success -> clear form + confirmation banner).
      setSupplyId("");
      setQuantity("");
      setConsumptionType("");
      setClinicId("");
      // Refresh products so current_stock reflects the new consumption if the
      // user registers another one right after.
      const refreshed = await listProducts();
      setProducts(refreshed);
    } catch (err) {
      // HTTP 400 insufficient stock -> ApiError.message already carries the
      // API's exact detail string ("Insufficient stock for supply '...'.
      // Available: X, requested: Y."). Rendered inline near quantity below,
      // not as a generic banner, per README.
      const message =
        err instanceof ApiError ? err.message : "Failed to log consumption. Please try again.";
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loadingProducts) {
    return <p className="p-6 text-gray-500">Loading medical supplies...</p>;
  }

  if (loadError) {
    return (
      <div className="p-6">
        <div className="rounded-md bg-red-50 border border-red-300 p-4 text-red-800">
          {loadError}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-lg">
      <h1 className="text-2xl font-semibold mb-2">Log Consumption</h1>
      <p className="text-sm text-gray-500 mb-6">
        Record a clinical consumption event for a medical supply.
      </p>

      {success && (
        <div className="mb-4 rounded-md bg-green-50 border border-green-300 p-4 text-green-800">
          Consumption logged successfully.
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div>
          <label htmlFor="supply" className="block text-sm font-medium mb-1">
            Medical Supply
          </label>
          <select
            id="supply"
            value={supplyId}
            onChange={(e) => setSupplyId(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">Select a supply...</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name} ({product.sku})
              </option>
            ))}
          </select>
        </div>

        {/* Reactive stock display — updates immediately when selection changes. */}
        {selectedProduct && (
          <div className="text-sm bg-gray-50 border border-gray-200 rounded-md px-3 py-2">
            Current stock for <span className="font-medium">{selectedProduct.name}</span>:{" "}
            <span className="font-semibold">{selectedProduct.current_stock}</span>
          </div>
        )}

        <div>
          <label htmlFor="quantity" className="block text-sm font-medium mb-1">
            Quantity
          </label>
          <input
            id="quantity"
            type="number"
            min={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          />

          {/* Client-side guard: quantity > displayed stock (UX only). */}
          {quantityExceedsStock && (
            <p className="text-sm text-amber-700 mt-1">
              Warning: this exceeds the current stock ({selectedProduct!.current_stock}
              ).
            </p>
          )}

          {/* API 400 insufficient-stock error, shown inline next to quantity per README. */}
          {submitError && <p className="text-sm text-red-700 mt-1">{submitError}</p>}
        </div>

        <div>
          <label htmlFor="consumptionType" className="block text-sm font-medium mb-1">
            Consumption Type
          </label>
          <select
            id="consumptionType"
            value={consumptionType}
            onChange={(e) => setConsumptionType(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">Select a type...</option>
            {(Object.keys(CONSUMPTION_TYPE_LABELS) as ConsumptionType[]).map((type) => (
              <option key={type} value={type}>
                {CONSUMPTION_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="clinic" className="block text-sm font-medium mb-1">
            Clinic
          </label>
          <select
            id="clinic"
            value={clinicId}
            onChange={(e) => setClinicId(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">Select a clinic...</option>
            {CLINIC_IDS.map((id) => (
              <option key={id} value={id}>
                Clinic {id}
              </option>
            ))}
          </select>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="mt-2 bg-gray-700 text-white font-medium px-4 py-2 rounded-md hover:bg-gray-800 disabled:opacity-50"
        >
          {submitting ? "Logging..." : "Log Consumption"}
        </button>

        <button
          type="button"
          onClick={() => router.push("/inventory/products")}
          className="text-sm text-gray-500 hover:underline"
        >
          Back to Medical Supplies
        </button>
      </form>
    </div>
  );
}