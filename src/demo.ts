import type { Candidate } from "./types/models";
import { filterCandidates, sortCandidates } from "./utils/collections";
import { linearSearchByEmail, binarySearchByName } from "./utils/search";
import { buildCandidateReport } from "./utils/transformations";
import { validateCandidateBatch } from "./utils/validations";

const sampleCandidates: Candidate[] = [
  { id: "1", full_name: "Ana Torres", email: "ana@example.com", phone: "+1 555 111 2222", position: "Registered Nurse", linkedin_url: null, cv_url: null, experience_years: 5, status: "selected", stage: "offer_presented", applied_at: "2026-01-10" },
  { id: "2", full_name: "Ben Carter", email: "ben@example.com", phone: "+1 555 222 3333", position: "Patient Coordinator", linkedin_url: null, cv_url: null, experience_years: 2, status: "in_progress", stage: "review", applied_at: "2026-02-01" },
  { id: "3", full_name: "Chloe Diaz", email: "chloe@example.com", phone: "+1 555 333 4444", position: "Registered Nurse", linkedin_url: null, cv_url: null, experience_years: 8, status: "selected", stage: "offer_presented", applied_at: "2026-01-20" },
  { id: "4", full_name: "Diego Ellis", email: "diego@example.com", phone: "+1 555 444 5555", position: "Clinic Operations Manager", linkedin_url: null, cv_url: null, experience_years: 12, status: "received", stage: "pending", applied_at: "2026-03-05" },
];

const output = document.getElementById("output")!;

function print(data: unknown) {
  output.textContent = JSON.stringify(data, null, 2);
}

document.getElementById("btn-filter")?.addEventListener("click", () => {
  const selected = filterCandidates(sampleCandidates, { status: "selected" });
  const sorted = sortCandidates(selected, "experience_years", "desc");
  print(sorted);
});

document.getElementById("btn-search")?.addEventListener("click", () => {
  const linearResult = linearSearchByEmail(sampleCandidates, "chloe@example.com");
  const sortedByName = sortCandidates(sampleCandidates, "full_name", "asc");
  const binaryIndex = binarySearchByName(sortedByName, "Diego Ellis");
  print({
    linearSearch: linearResult,
    binarySearchIndex: binaryIndex,
    binarySearchResult: binaryIndex >= 0 ? sortedByName[binaryIndex] : null,
  });
});

document.getElementById("btn-report")?.addEventListener("click", () => {
  print(buildCandidateReport(sampleCandidates));
});

document.getElementById("btn-validate")?.addEventListener("click", () => {
  const batch = [
    { full_name: "Eva Frank", email: "not-an-email", phone: "555", position: "", experience_years: -1 },
    { full_name: "Frank Gomez", email: "frank@example.com", phone: "+1 555 555 6666", position: "Registered Nurse", experience_years: 3 },
  ];
  print(validateCandidateBatch(batch));
});