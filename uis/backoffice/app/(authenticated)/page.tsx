"use client";

import { calculateCandidateStats } from "@/lib/candidateStats";

export default function BackofficeHome() {
  const stats = calculateCandidateStats({
    totalCandidates: 42,
    selected: 9,
    discarded: 15,
  });

  return (
    <div className="max-w-2xl">
      <p className="mb-[10px] inline-block text-[0.78rem] font-extrabold uppercase tracking-[0.14em] text-[#ff6a3d]">People &amp; Talent</p>
      <h2 className="mb-6 font-[family-name:var(--font-space-grotesk)] text-2xl tracking-[-0.03em]">Candidate stats overview</h2>

      <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-3">
        <div className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-[linear-gradient(135deg,rgba(255,106,61,0.18),rgba(255,255,255,0.95)),#ffffff] p-7 text-center shadow-[0_20px_50px_rgba(16,16,16,0.08)]">
          <strong className="font-[family-name:var(--font-space-grotesk)] text-[2.2rem] tracking-[-0.05em] text-[#ff6a3d]">{stats.totalCandidates}</strong>
          <p className="mt-2 text-sm text-[#5f5a54]">Total candidates</p>
        </div>
        <div className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white p-7 text-center shadow-[0_20px_50px_rgba(16,16,16,0.08)]">
          <strong className="font-[family-name:var(--font-space-grotesk)] text-[2.2rem] tracking-[-0.05em]">{stats.selectionRate}%</strong>
          <p className="mt-2 text-sm text-[#5f5a54]">Selection rate</p>
        </div>
        <div className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-[#171717] p-7 text-center text-white shadow-[0_20px_50px_rgba(16,16,16,0.08)]">
          <strong className="font-[family-name:var(--font-space-grotesk)] text-[2.2rem] tracking-[-0.05em]">{stats.discardRate}%</strong>
          <p className="mt-2 text-sm text-[rgba(255,255,255,0.72)]">Discard rate</p>
        </div>
      </div>
    </div>
  );
}