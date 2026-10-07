import { Suspense } from "react";
import ReportingDashboard from "@/components/ReportingDashboard";

export default function ReportingPage() {
  return (
    <Suspense fallback={<p className="text-gray-500">Loading...</p>}>
      <ReportingDashboard />
    </Suspense>
  );
}