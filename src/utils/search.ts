import type { Candidate } from "../types/models";

/**
 * Linear search: works on unsorted arrays.
 * Returns the first candidate whose email matches, or null if not found.
 */
export function linearSearchByEmail(
  candidates: Candidate[],
  email: string
): Candidate | null {
  for (const candidate of candidates) {
    if (candidate.email.toLowerCase() === email.toLowerCase()) {
      return candidate;
    }
  }
  return null;
}

/**
 * Binary search: requires the array to be pre-sorted by full_name (ascending).
 * Returns the index of the match, or -1 if not found.
 */
export function binarySearchByName(
  sortedCandidates: Candidate[],
  fullName: string
): number {
  let low = 0;
  let high = sortedCandidates.length - 1;
  const target = fullName.toLowerCase();

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const midName = sortedCandidates[mid].full_name.toLowerCase();

    if (midName === target) {
      return mid;
    }
    if (midName < target) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return -1;
}