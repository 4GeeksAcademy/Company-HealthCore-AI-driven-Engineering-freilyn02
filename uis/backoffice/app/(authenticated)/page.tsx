"use client";

import { calculateCandidateStats } from "@/lib/candidateStats";

export default function BackofficeHome() {
  const stats = calculateCandidateStats({
    totalCandidates: 42,
    selected: 9,
    discarded: 15,
  });

  return (
    <div className="max-w-xl">
      <h2 className="text-xl font-semibold mb-4">Candidate stats overview</h2>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white border border-gray-200 rounded-md p-4 text-center">
          <p className="text-2xl font-bold text-blue-700">
            {stats.totalCandidates}
          </p>
          <p className="text-sm text-gray-500">Total candidates</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-md p-4 text-center">
          <p className="text-2xl font-bold text-green-600">
            {stats.selectionRate}%
          </p>
          <p className="text-sm text-gray-500">Selection rate</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-md p-4 text-center">
          <p className="text-2xl font-bold text-red-600">
            {stats.discardRate}%
          </p>
          <p className="text-sm text-gray-500">Discard rate</p>
        </div>
      </div>
    </div>
  );
}