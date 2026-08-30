import type { Candidate, CandidateStatus, CandidateReport } from "../types/models";

/**
 * Counts candidates grouped by status.
 */
export function countByStatus(candidates: Candidate[]): Record<CandidateStatus, number> {
  const counts: Record<CandidateStatus, number> = {
    received: 0,
    in_progress: 0,
    selected: 0,
    discarded: 0,
  };

  for (const candidate of candidates) {
    counts[candidate.status] += 1;
  }

  return counts;
}

/**
 * Calculates the average years of experience across candidates.
 * Returns 0 for an empty array.
 */
export function averageExperienceYears(candidates: Candidate[]): number {
  if (candidates.length === 0) return 0;
  const total = candidates.reduce((sum, c) => sum + c.experience_years, 0);
  return Number((total / candidates.length).toFixed(1));
}

/**
 * Finds the candidate with the most years of experience.
 * Returns null for an empty array.
 */
export function mostExperiencedCandidate(candidates: Candidate[]): Candidate | null {
  if (candidates.length === 0) return null;
  return candidates.reduce((max, current) =>
    current.experience_years > max.experience_years ? current : max
  );
}

/**
 * Finds the candidate with the least years of experience.
 * Returns null for an empty array.
 */
export function leastExperiencedCandidate(candidates: Candidate[]): Candidate | null {
  if (candidates.length === 0) return null;
  return candidates.reduce((min, current) =>
    current.experience_years < min.experience_years ? current : min
  );
}

/**
 * Builds a full summary report for a set of candidates.
 */
export function buildCandidateReport(candidates: Candidate[]): CandidateReport {
  const byStatus = countByStatus(candidates);
  const experienceValues = candidates.map((c) => c.experience_years);

  return {
    totalCandidates: candidates.length,
    byStatus,
    averageExperienceYears: averageExperienceYears(candidates),
    maxExperienceYears: experienceValues.length > 0 ? Math.max(...experienceValues) : 0,
    minExperienceYears: experienceValues.length > 0 ? Math.min(...experienceValues) : 0,
  };
}