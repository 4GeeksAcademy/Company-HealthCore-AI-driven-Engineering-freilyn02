// Types for the knowledge base assistant (POST /knowledge/query).

// Same limit as the API (MAX_QUESTION_CHARS in services/api/routers/knowledge.py).
export const MAX_QUESTION_CHARS = 500;

export interface KnowledgeQueryResponse {
  answer: string;
}

// The four states of the query UI.
export type KnowledgeStatus = "idle" | "loading" | "success" | "error";