// app/(authenticated)/inventory/orders/page.tsx
"use client";

import { useEffect, useState } from "react";
import { listOrders } from "@/lib/inventory";
import { ApiError } from "@/lib/api";
import type { InventoryOrderHistoryItem } from "@/types/inventory";

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function OrdersHistoryPage() {
  const [orders, setOrders] = useState<InventoryOrderHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await listOrders();
        setOrders(data);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Failed to load order history.";
        setError(message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return <p className="p-6 text-gray-500">Loading order history...</p>;
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-md bg-red-50 border border-red-300 p-4 text-red-800">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-6">Order History</h1>

      {orders.length === 0 ? (
        <p className="text-gray-500">No orders found.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full border border-gray-200 rounded-lg overflow-hidden">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  Type
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  Supply
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  Quantity
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  Clinic
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  Detail
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  Date
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">
                  User UUID
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {orders.map((order) => (
                <tr key={`${order.order_type}-${order.id}`}>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs font-medium px-2 py-1 rounded-full ${
                        order.order_type === "inbound"
                          ? "bg-blue-100 text-blue-800 border border-blue-300"
                          : "bg-gray-100 text-gray-800 border border-gray-300"
                      }`}
                    >
                      {order.order_type === "inbound" ? "Delivery" : "Consumption"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {order.supply_name}{" "}
                    <span className="text-gray-400">({order.supply_sku})</span>
                  </td>
                  <td className="px-4 py-3 text-sm">{order.quantity}</td>
                  <td className="px-4 py-3 text-sm">Clinic {order.clinic_id}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {order.order_type === "inbound"
                      ? order.vendor_name
                      : order.consumption_type === "clinical_use"
                        ? "Clinical Use"
                        : "Expiry / Waste"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {formatDate(order.created_at)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 font-mono">
                    {order.user_uuid}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}