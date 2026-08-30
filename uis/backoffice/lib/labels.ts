import { SupplierStatus } from "../types/supplier";

export const STATUS_LABELS: Record<SupplierStatus, string> = {
  active: "Active",
  suspended: "Suspended",
};

export const STATUS_OPTIONS: SupplierStatus[] = ["active", "suspended"];