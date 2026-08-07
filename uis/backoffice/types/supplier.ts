export type SupplierStatus = "active" | "suspended";
export type SupplierCountry = "US" | "UK";

export const SUPPLIER_CATEGORIES = [
  "Medical Equipment",
  "Pharmaceuticals",
  "PPE & Medical Consumables",
  "Lab Supplies",
  "IT & Telehealth Equipment",
  "Facility & Maintenance",
  "Office & Administrative Supplies",
] as const;

export type SupplierCategory = (typeof SUPPLIER_CATEGORIES)[number];

export interface Supplier {
  id: number;
  name: string;
  country: SupplierCountry;
  categories: SupplierCategory[];
  rate: number;
  status: SupplierStatus;
  updated_at: string;
}

export interface SupplierCreateInput {
  name: string;
  country: SupplierCountry;
  categories: SupplierCategory[];
  rate: number;
  status?: SupplierStatus;
}