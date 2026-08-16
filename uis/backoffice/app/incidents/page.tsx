import { Suspense } from "react";
import IncidentList from "../../components/IncidentList";

export default function IncidentsPage() {
  return (
    <Suspense fallback={<p className="text-gray-500">Loading...</p>}>
      <IncidentList />
    </Suspense>
  );
}