import { Suspense } from "react";
import SupplierList from "../../components/SupplierList";

export default function SuppliersPage() {
  return (
    <Suspense fallback={<p className="text-gray-500">Loading...</p>}>
      <SupplierList />
    </Suspense>
  );
}