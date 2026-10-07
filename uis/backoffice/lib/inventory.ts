// lib/inventory.ts
//
// Centralized module for all /inventory API calls (per project README:
// "no fetch in components"). Mirrors the pattern in lib/api.ts, but points
// at NEXT_PUBLIC_INVENTORY_API_URL instead of NEXT_PUBLIC_API_URL.

import { getToken, clearToken } from "./auth";
import { ApiError } from "./api";
import type {
  MedicalSupply,
  SupplyDeliveryCreate,
  SupplyDelivery,
  SupplyConsumptionCreate,
  SupplyConsumption,
  InventoryOrderHistoryItem,
} from "@/types/inventory";

const INVENTORY_API_URL = process.env.NEXT_PUBLIC_INVENTORY_API_URL;

async function inventoryFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const base = INVENTORY_API_URL!.replace(/\/$/, "");
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options?.headers,
  };

  const res = await fetch(`${base}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearToken();
    window.location.assign("/login");
    throw new ApiError("Unauthorized", 401);
  }

  if (!res.ok) {
    let message = res.statusText;
    let field: string | undefined;
    try {
      const body = await res.json();
      if (body.field && body.message) {
        field = body.field;
        message = body.message;
      } else if (body.detail) {
        message = body.detail;
      }
    } catch {
      // response had no JSON body
    }
    throw new ApiError(message, res.status, field);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const listProducts = () =>
  inventoryFetch<MedicalSupply[]>("/inventory/products");

export const getProduct = (id: number) =>
  inventoryFetch<MedicalSupply>(`/inventory/products/${id}`);

export const createInboundOrder = (body: SupplyDeliveryCreate) =>
  inventoryFetch<SupplyDelivery>("/inventory/orders/inbound", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const createOutboundOrder = (body: SupplyConsumptionCreate) =>
  inventoryFetch<SupplyConsumption>("/inventory/orders/outbound", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listOrders = () =>
  inventoryFetch<InventoryOrderHistoryItem[]>("/inventory/orders");