"use client";

import { useState } from "react";
import { ApiError } from "../lib/api";
import { askKnowledgeBase } from "../services/knowledge";
import { KnowledgeStatus, MAX_QUESTION_CHARS } from "../types/knowledge";

const EXAMPLE_QUESTIONS = [
  "Will I be charged a no-show fee if I am on Medicare?",
  "Do you accept Humana?",
  "What documents should I bring to my first appointment?",
];

export default function KnowledgeAssistant() {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<KnowledgeStatus>("idle");
  const [answer, setAnswer] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const loading = status === "loading";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;

    const trimmed = question.trim();
    if (!trimmed) {
      setErrorMessage("Please type a question first.");
      setStatus("error");
      return;
    }

    setStatus("loading");
    setAnswer("");
    setErrorMessage("");
    try {
      const result = await askKnowledgeBase(trimmed);
      setAnswer(result.answer);
      setStatus("success");
    } catch (err) {
      if (err instanceof ApiError && typeof err.message === "string" && err.message) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Could not reach the assistant. Please try again in a moment.");
      }
      setStatus("error");
    }
  }

  return (
    <section className="max-w-2xl">
      <h2 className="mb-1 font-[family-name:var(--font-space-grotesk)] text-2xl tracking-[-0.03em]">
        Knowledge Assistant
      </h2>
      <p className="mb-6 text-sm text-[#5f5a54]">
        Ask about insurance coverage, appointments, referrals or what new patients need to bring.
        Answers come only from HealthCore&apos;s internal documents.
      </p>

      <form
        onSubmit={handleSubmit}
        className="mb-6 rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white p-6 shadow-[0_14px_30px_rgba(16,16,16,0.05)]"
      >
        <label htmlFor="knowledge-question" className="mb-1 block text-sm text-[#5f5a54]">
          Your question
        </label>
        {/* Same rule as the incident form: no patient-identifying data in free text */}
        <p className="mb-1.5 rounded-lg border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-1.5 text-xs font-semibold text-[#b3261e]">
          ⚠ Do not enter any patient-identifying information (name, date of birth, medical
          record number, member ID or contact details).
        </p>
        <textarea
          id="knowledge-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={MAX_QUESTION_CHARS}
          rows={3}
          disabled={loading}
          className="w-full rounded-xl border border-[rgba(16,16,16,0.14)] px-4 py-2 outline-none transition focus:border-[#ff6a3d] focus:ring-2 focus:ring-[#ff6a3d]/20 disabled:opacity-60"
        />
        <div className="mt-1 text-right text-xs text-[#5f5a54]">
          {question.length}/{MAX_QUESTION_CHARS}
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((example) => (
            <button
              key={example}
              type="button"
              disabled={loading}
              onClick={() => setQuestion(example)}
              className="rounded-full border border-[rgba(16,16,16,0.14)] px-3 py-1 text-xs text-[#5f5a54] transition hover:border-[#ff6a3d] hover:text-[#ff6a3d] disabled:opacity-50"
            >
              {example}
            </button>
          ))}
        </div>

        <button
          type="submit"
          disabled={loading}
          className="rounded-full bg-[#ff6a3d] px-5 py-3 font-extrabold text-white transition hover:-translate-y-0.5 hover:bg-[#e4542c] disabled:opacity-50"
        >
          {loading ? "Searching..." : "Ask"}
        </button>
      </form>

      {/* Result area: announced to screen readers when it changes */}
      <div aria-live="polite">
        {status === "idle" && (
          <p className="text-sm text-[#5f5a54]">
            Type a question or pick an example, then press Ask.
          </p>
        )}

        {status === "loading" && (
          <p className="text-sm text-[#5f5a54]">Searching the knowledge base...</p>
        )}

        {status === "success" && (
          <div className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-white p-6 shadow-[0_14px_30px_rgba(16,16,16,0.05)]">
            <h3 className="mb-2 font-[family-name:var(--font-space-grotesk)] text-lg tracking-[-0.03em]">
              Answer
            </h3>
            <p className="whitespace-pre-wrap">{answer}</p>
          </div>
        )}

        {status === "error" && (
          <p className="rounded-xl border border-[#b3261e]/20 bg-[#b3261e]/5 px-3 py-2 text-sm font-semibold text-[#b3261e]">
            {errorMessage}
          </p>
        )}
      </div>
    </section>
  );
}