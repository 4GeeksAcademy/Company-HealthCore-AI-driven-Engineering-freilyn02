// app/(authenticated)/inventory/orders/inbound/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { listProducts, createInboundOrder } from "@/lib/inventory";
import { ApiError } from "@/lib/api";
import type { MedicalSupply } from "@/types/inventory";

// Clinic IDs range from 1-12 (9 US clinics, 3 UK clinics) per CONTEXT-healthcore.md.
const CLINIC_IDS = Array.from({ length: 12 }, (_, i) => i + 1);

export default function InboundOrderPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [products, setProducts] = useState<MedicalSupply[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [supplyId, setSupplyId] = useState<string>(searchParams.get("supply_id") ?? "");
  const [quantity, setQuantity] = useState<string>("");
  const [vendorName, setVendorName] = useState<string>("");
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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    setSuccess(false);

    if (!supplyId || !quantity || !vendorName || !clinicId) {
      setSubmitError("Please fill in all fields.");
      return;
    }

    setSubmitting(true);
    try {
      await createInboundOrder({
        supply_id: Number(supplyId),
        quantity: Number(quantity),
        vendor_name: vendorName,
        clinic_id: Number(clinicId),
      });
      setSuccess(true);
      // Clear the form (README requirement: success -> clear form + confirmation banner).
      setSupplyId("");
      setQuantity("");
      setVendorName("");
      setClinicId("");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to register delivery. Please try again.";
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
      <h1 className="text-2xl font-semibold mb-2">Register Delivery</h1>
      <p className="text-sm text-gray-500 mb-6">
        Log a vendor shipment received at a HealthCore clinic.
      </p>

      {success && (
        <div className="mb-4 rounded-md bg-green-50 border border-green-300 p-4 text-green-800">
          Delivery registered successfully.
        </div>
      )}

      {submitError && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-300 p-4 text-red-800">
          {submitError}
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
        </div>

        <div>
          <label htmlFor="vendor" className="block text-sm font-medium mb-1">
            Vendor Name
          </label>
          <input
            id="vendor"
            type="text"
            placeholder="e.g. MedLine Industries"
            value={vendorName}
            onChange={(e) => setVendorName(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          />
        </div>

        <div>
          <label htmlFor="clinic" className="block text-sm font-medium mb-1">
            Receiving Clinic
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
          className="mt-2 bg-blue-600 text-white font-medium px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "Registering..." : "Register Delivery"}
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