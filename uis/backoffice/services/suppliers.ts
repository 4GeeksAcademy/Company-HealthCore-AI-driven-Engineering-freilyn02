import { apiFetch } from "../lib/api";
import { Supplier, SupplierCreateInput, SupplierStatus } from "../types/supplier";

export interface SupplierFilters {
  country?: string;
  category?: string;
}

export function getSuppliers(filters: SupplierFilters = {}): Promise<Supplier[]> {
  const params = new URLSearchParams();
  if (filters.country) params.set("country", filters.country);
  if (filters.category) params.set("category", filters.category);
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<Supplier[]>(`/suppliers${query}`);
}

export function createSupplier(data: SupplierCreateInput): Promise<Supplier> {
  return apiFetch<Supplier>("/suppliers", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function patchRate(id: number, rate: number): Promise<Supplier> {
  return apiFetch<Supplier>(`/suppliers/${id}/rate`, {
    method: "PATCH",
    body: JSON.stringify({ rate }),
  });
}

export function patchStatus(id: number, status: SupplierStatus): Promise<Supplier> {
  return apiFetch<Supplier>(`/suppliers/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}