export type CandidateStatus = "received" | "in_progress" | "selected" | "discarded";
export type CandidateStage =
  | "pending"
  | "review"
  | "personal_interview"
  | "technical_interview"
  | "offer_presented";

export interface Candidate {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  position: string;
  linkedin_url: string | null;
  cv_url: string | null;
  experience_years: number;
  status: CandidateStatus;
  stage: CandidateStage;
  applied_at: string;
}

export interface CandidateReport {
  totalCandidates: number;
  byStatus: Record<CandidateStatus, number>;
  averageExperienceYears: number;
  maxExperienceYears: number;
  minExperienceYears: number;
}