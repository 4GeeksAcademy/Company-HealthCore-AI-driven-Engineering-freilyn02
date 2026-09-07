// types/inventory.ts
//
// Mirrors services/api/inventory_schemas.py exactly.
// current_stock is always computed server-side -- never sent by the client.

export type SupplyCategory =
  | "ppe"
  | "wound_care"
  | "diagnostics"
  | "medications"
  | "consumables";

export type SupplyUnit = "box" | "unit" | "pack" | "vial";

export type SupplyCountry = "US" | "UK";

export type ConsumptionType = "clinical_use" | "expiry_waste";

export interface MedicalSupply {
  id: number;
  name: string;
  sku: string;
  category: SupplyCategory;
  unit: SupplyUnit;
  country: SupplyCountry;
  current_stock: number;
}

export interface SupplyDeliveryCreate {
  supply_id: number;
  quantity: number;
  vendor_name: string;
  clinic_id: number;
}

export interface SupplyDelivery {
  id: number;
  supply_id: number;
  quantity: number;
  vendor_name: string;
  clinic_id: number;
  created_at: string;
  user_uuid: string;
}

export interface SupplyConsumptionCreate {
  supply_id: number;
  quantity: number;
  consumption_type: ConsumptionType;
  clinic_id: number;
}

export interface SupplyConsumption {
  id: number;
  supply_id: number;
  quantity: number;
  consumption_type: ConsumptionType;
  clinic_id: number;
  created_at: string;
  user_uuid: string;
}

export interface InventoryOrderHistoryItem {
  id: number;
  order_type: "inbound" | "outbound";
  supply_id: number;
  supply_name: string;
  supply_sku: string;
  quantity: number;
  clinic_id: number;
  user_uuid: string;
  created_at: string;
  vendor_name?: string;
  consumption_type?: ConsumptionType;
}