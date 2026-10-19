import { apiFetch } from "../lib/api";
import { KnowledgeQueryResponse } from "../types/knowledge";

// POST /knowledge/query -> { answer }
export function askKnowledgeBase(question: string): Promise<KnowledgeQueryResponse> {
  return apiFetch<KnowledgeQueryResponse>("/knowledge/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}