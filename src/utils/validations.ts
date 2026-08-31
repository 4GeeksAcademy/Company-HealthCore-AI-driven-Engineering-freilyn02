import type { Candidate } from "../types/models";

export interface ValidationResult {
  isValid: boolean;
  errors: string[];
}

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const urlPattern = /^https?:\/\/.+\..+/;

/**
 * Validates a candidate record against HealthCore's business rules
 * before it is processed or stored.
 */
export function validateCandidate(
  candidate: Partial<Candidate>
): ValidationResult {
  const errors: string[] = [];

  if (!candidate.full_name || candidate.full_name.trim().length < 2) {
    errors.push("full_name is required and must be at least 2 characters.");
  }

  if (!candidate.email || !emailPattern.test(candidate.email)) {
    errors.push("email is required and must be a valid email address.");
  }

  if (!candidate.phone || candidate.phone.trim().length < 7) {
    errors.push("phone is required and must be a valid phone number.");
  }

  if (!candidate.position || candidate.position.trim().length === 0) {
    errors.push("position is required.");
  }

  if (
    candidate.experience_years === undefined ||
    candidate.experience_years < 0
  ) {
    errors.push("experience_years is required and must be 0 or greater.");
  }

  if (candidate.linkedin_url && !urlPattern.test(candidate.linkedin_url)) {
    errors.push("linkedin_url must be a valid URL if provided.");
  }

  if (candidate.cv_url && !urlPattern.test(candidate.cv_url)) {
    errors.push("cv_url must be a valid URL if provided.");
  }

  return {
    isValid: errors.length === 0,
    errors,
  };
}

/**
 * Validates a whole batch of candidates, returning only the invalid ones
 * paired with their specific errors.
 */
export function validateCandidateBatch(
  candidates: Partial<Candidate>[]
): { candidate: Partial<Candidate>; result: ValidationResult }[] {
  return candidates
    .map((candidate) => ({ candidate, result: validateCandidate(candidate) }))
    .filter(({ result }) => !result.isValid);
}