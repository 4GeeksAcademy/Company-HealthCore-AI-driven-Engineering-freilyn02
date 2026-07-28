import Link from "next/link";

export default function Home() {
  return (
    <div className="px-6 py-20 max-w-4xl mx-auto text-center">
      <h1 className="text-4xl font-bold text-blue-700 mb-4">
        Continuity, not just convenience.
      </h1>
      <p className="text-lg text-gray-600 mb-8">
        HealthCore is an outpatient clinic network across the US and UK,
        connecting 12 clinics through a shared digital backbone — so your
        care history follows you, wherever you visit.
      </p>
      <div className="flex justify-center gap-4">
        <Link
          href="/clinics"
          className="bg-blue-700 text-white px-6 py-3 rounded-md font-medium"
        >
          Find a clinic
        </Link>
        <Link
          href="/about"
          className="border border-blue-700 text-blue-700 px-6 py-3 rounded-md font-medium"
        >
          Our story
        </Link>
      </div>
    </div>
  );
}