// app/(authenticated)/inventory/products/page.tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listProducts } from "@/lib/inventory";
import { ApiError } from "@/lib/api";
import type { MedicalSupply } from "@/types/inventory";

// Stock-level thresholds (README requirement: define thresholds in a code comment).
// current_stock <= 5   -> low (red)
// current_stock <= 15  -> warning (amber)
// otherwise            -> healthy (green)
function getStockLevel(currentStock: number): "low" | "warning" | "healthy" {
  if (currentStock <= 5) return "low";
  if (currentStock <= 15) return "warning";
  return "healthy";
}

const STOCK_BADGE_STYLES: Record<string, string> = {
  low: "bg-red-100 text-red-800 border border-red-300",
  warning: "bg-amber-100 text-amber-800 border border-amber-300",
  healthy: "bg-green-100 text-green-800 border border-green-300",
};

const STOCK_BADGE_LABELS: Record<string, string> = {
  low: "Low stock",
  warning: "Warning",
  healthy: "Healthy",
};

// Human-readable labels for category codes coming from the API,
// per CONTEXT-healthcore.md entity spec.
const CATEGORY_LABELS: Record<string, string> = {
  ppe: "PPE",
  wound_care: "Wound Care",
  diagnostics: "Diagnostics",
  medications: "Medications",
  consumables: "Consumables",
};

export default function ProductsPage() {
  const [products, setProducts] = useState<MedicalSupply[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await listProducts();
        setProducts(data);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Failed to load medical supplies.";
        setError(message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return <p className="p-6 text-gray-500">Loading medical supplies...</p>;
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-md bg-red-50 border border-red-300 p-4 text-red-800">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-6">Medical Supplies</h1>

      {products.length === 0 ? (
        <p className="text-gray-500">No medical supplies found.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {products.map((product) => {
            const level = getStockLevel(product.current_stock);
            return (
              <div
                key={product.id}
                className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm flex flex-col gap-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-semibold text-lg">{product.name}</h2>
                  <span
                    className={`text-xs font-medium px-2 py-1 rounded-full whitespace-nowrap ${STOCK_BADGE_STYLES[level]}`}
                  >
                    {STOCK_BADGE_LABELS[level]}
                  </span>
                </div>

                <p className="text-sm text-gray-500">SKU: {product.sku}</p>

                <div className="flex flex-wrap gap-2 text-xs text-gray-600">
                  <span className="bg-gray-100 px-2 py-1 rounded">
                    {CATEGORY_LABELS[product.category] ?? product.category}
                  </span>
                  <span className="bg-gray-100 px-2 py-1 rounded">{product.unit}</span>
                  <span className="bg-gray-100 px-2 py-1 rounded">{product.country}</span>
                </div>

                <p className="text-sm mt-1">
                  Current stock: <span className="font-semibold">{product.current_stock}</span>
                </p>

                <div className="flex gap-2 mt-3">
                  <Link
                    href={`/inventory/orders/inbound?supply_id=${product.id}`}
                    className="flex-1 text-center text-sm font-medium px-3 py-2 rounded-md bg-blue-600 text-white hover:bg-blue-700"
                  >
                    Register Delivery
                  </Link>
                  <Link
                    href={`/inventory/orders/outbound?supply_id=${product.id}`}
                    className="flex-1 text-center text-sm font-medium px-3 py-2 rounded-md bg-gray-700 text-white hover:bg-gray-800"
                  >
                    Log Consumption
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}