import type { Candidate, CandidateStatus, CandidateStage } from "../types/models";

export interface CandidateFilters {
  status?: CandidateStatus;
  stage?: CandidateStage;
  position?: string;
  minExperienceYears?: number;
}

/**
 * Filters candidates by any combination of status, stage, position, and minimum experience.
 */
export function filterCandidates(
  candidates: Candidate[],
  filters: CandidateFilters
): Candidate[] {
  return candidates.filter((candidate) => {
    if (filters.status && candidate.status !== filters.status) return false;
    if (filters.stage && candidate.stage !== filters.stage) return false;
    if (filters.position && candidate.position !== filters.position) return false;
    if (
      filters.minExperienceYears !== undefined &&
      candidate.experience_years < filters.minExperienceYears
    ) {
      return false;
    }
    return true;
  });
}

export type SortField = "full_name" | "experience_years" | "applied_at";
export type SortDirection = "asc" | "desc";

/**
 * Sorts candidates by a given field and direction, without mutating the original array.
 */
export function sortCandidates(
  candidates: Candidate[],
  field: SortField,
  direction: SortDirection = "asc"
): Candidate[] {
  const sorted = [...candidates].sort((a, b) => {
    const valueA = a[field];
    const valueB = b[field];

    if (valueA < valueB) return direction === "asc" ? -1 : 1;
    if (valueA > valueB) return direction === "asc" ? 1 : -1;
    return 0;
  });

  return sorted;
}

/**
 * Groups candidates by an arbitrary key (e.g. status, stage, or position).
 */
export function groupCandidatesBy<K extends keyof Candidate>(
  candidates: Candidate[],
  key: K
): Record<string, Candidate[]> {
  return candidates.reduce<Record<string, Candidate[]>>((groups, candidate) => {
    const groupKey = String(candidate[key]);
    if (!groups[groupKey]) {
      groups[groupKey] = [];
    }
    groups[groupKey].push(candidate);
    return groups;
  }, {});
}