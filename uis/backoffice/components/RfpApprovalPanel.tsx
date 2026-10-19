"use client";

import { useEffect, useState } from "react";
import {
  getMyApprover,
  getRfpApprovals,
  getRfpFinalDocument,
  getRfpTrace,
  startRfpApprovals,
  submitRfpDecision,
} from "@/lib/rfp";
import type {
  ApprovalStatus,
  RfpApprovalBoard,
  RfpApproverIdentity,
  RfpArbitrationResolution,
  RfpTicket,
  RfpTraceEvent,
} from "@/types/rfp";

const DEPARTMENT_LABELS: Record<string, string> = {
  revenue: "Revenue Cycle",
  clinical: "Clinical Operations",
  compliance: "Compliance and Data Governance",
};

const APPROVAL_STYLES: Record<ApprovalStatus, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  changes_requested: "bg-orange-100 text-orange-800",
};

const APPROVAL_LABELS: Record<ApprovalStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  changes_requested: "Changes requested",
};

type FormMode = "request_changes" | "reject" | null;

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function ApprovalBadge({ status }: { status: ApprovalStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${APPROVAL_STYLES[status] ?? ""}`}>
      {APPROVAL_LABELS[status] ?? status}
    </span>
  );
}

export default function RfpApprovalPanel({
  ticket,
  onChanged,
}: {
  ticket: RfpTicket;
  onChanged: () => void;
}) {
  const [board, setBoard] = useState<RfpApprovalBoard | null>(null);
  const [identity, setIdentity] = useState<RfpApproverIdentity | null>(null);
  const [resolutions, setResolutions] = useState<RfpArbitrationResolution[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<FormMode>(null);
  const [text, setText] = useState("");
  const [trace, setTrace] = useState<RfpTraceEvent[] | null>(null);
  const [finalDoc, setFinalDoc] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const canStart =
    (ticket.status === "under_evaluation" || ticket.status === "needs_human_review") &&
    ticket.routing_status === "ready_for_part3";
  const showBoard = ticket.status === "waiting_for_approval" || ticket.status === "done";

  useEffect(() => {
    let cancelled = false;
    getMyApprover()
      .then((who) => {
        if (!cancelled) setIdentity(who);
      })
      .catch(() => {
        if (!cancelled) setIdentity({ actor: null, department: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Loads the board with a plain promise chain (no synchronous setState in the effect body).
  // `reloadKey` forces a refetch after a decision even when the ticket status does not change.
  useEffect(() => {
    if (!showBoard) return;
    let cancelled = false;
    getRfpApprovals(ticket.id)
      .then((result) => {
        if (cancelled) return;
        setBoard(result);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err, "Could not load the approvals."));
      });
    return () => {
      cancelled = true;
    };
  }, [showBoard, ticket.id, ticket.status, reloadKey]);

  async function handleStart() {
    setBusy(true);
    setError(null);
    try {
      const result = await startRfpApprovals(ticket.id);
      setResolutions(result.resolutions ?? []);
      setReloadKey((key) => key + 1);
      onChanged();
    } catch (err) {
      setError(errorMessage(err, "Could not start the approvals."));
    } finally {
      setBusy(false);
    }
  }

  async function handleDecision(department: string, decision: "approve" | "reject" | "request_changes") {
    if (!identity?.actor) return;
    const value = text.trim();
    if (decision === "request_changes" && !value) {
      setError("Describe the changes you are requesting.");
      return;
    }
    if (decision === "reject" && !value) {
      setError("A comment is required to reject a section.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await submitRfpDecision(ticket.id, {
        department,
        decision,
        actor: identity.actor,
        ...(decision === "request_changes" ? { requested_changes: value } : {}),
        ...(decision === "reject" ? { comment: value } : {}),
      });
      setResolutions(result.resolutions ?? []);
      setMode(null);
      setText("");
      setTrace(null);
      setReloadKey((key) => key + 1);
      onChanged();
    } catch (err) {
      setError(errorMessage(err, "Could not record the decision."));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleTrace() {
    if (trace) {
      setTrace(null);
      return;
    }
    try {
      setTrace(await getRfpTrace(ticket.id));
    } catch (err) {
      setError(errorMessage(err, "Could not load the trace."));
    }
  }

  async function handleViewDocument() {
    if (finalDoc) {
      setFinalDoc(null);
      return;
    }
    try {
      setFinalDoc(await getRfpFinalDocument(ticket.id));
    } catch (err) {
      setError(errorMessage(err, "Could not load the final document."));
    }
  }

  function handleDownload() {
    if (!finalDoc) return;
    const url = URL.createObjectURL(new Blob([finalDoc], { type: "text/markdown" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `final_doc_${ticket.id}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  // The board only counts while the ticket is in a status that shows it.
  const approvals = showBoard ? board?.approvals : undefined;

  return (
    <section aria-label="Approvals" className="flex flex-col gap-3 rounded border border-gray-300 p-3">
      <h3 className="font-medium">Approvals</h3>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      {canStart && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-gray-600">
            The drafts are ready. Starting opens one approval per department; each owner decides on their own
            section.
          </p>
          <button
            type="button"
            onClick={() => void handleStart()}
            disabled={busy}
            className="w-fit rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {busy ? "Starting..." : "Start approvals"}
          </button>
        </div>
      )}

      {resolutions.length > 0 && (
        <div role="status" className="rounded border border-yellow-300 bg-yellow-50 p-2 text-xs text-yellow-900">
          <p className="font-medium">Arbitration applied</p>
          <ul className="list-disc pl-5">
            {resolutions.map((res) => (
              <li key={res.conflict_id}>
                {res.conflict_id} (arbiter: {res.arbiter}): {res.resolution}
              </li>
            ))}
          </ul>
        </div>
      )}

      {approvals?.blocked && (
        <p role="alert" className="rounded bg-red-50 p-2 text-sm text-red-800">
          A section reached the revision limit and was rejected. The final document cannot be generated until a
          new draft is produced.
        </p>
      )}

      {approvals && (
        <div className="grid gap-3 md:grid-cols-3">
          {Object.entries(approvals.departments).map(([department, info]) => {
            const pending = board?.pending.find((item) => item.department === department);
            const mine = identity?.department === department && pending !== undefined;
            return (
              <article key={department} className="flex flex-col gap-2 rounded border border-gray-300 p-3">
                <header className="flex items-center justify-between gap-2">
                  <h4 className="text-sm font-medium">{DEPARTMENT_LABELS[department] ?? department}</h4>
                  <ApprovalBadge status={info.approval_status} />
                </header>
                <p className="text-xs text-gray-500">
                  {info.approver ? `Approved by ${info.approver}` : "Not approved yet"} - revisions:{" "}
                  {info.revision_count}
                </p>

                {pending && (
                  <>
                    <p className="whitespace-pre-wrap text-sm">{pending.section_summary}</p>
                    <p className="text-xs text-gray-500">
                      Awaiting {pending.owner}
                      {pending.evaluation_snapshot.passed === false ? " - automatic evaluation did not pass" : ""}
                    </p>
                  </>
                )}

                {mine && (
                  <div className="flex flex-col gap-2">
                    {mode === null ? (
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleDecision(department, "approve")}
                          className="rounded bg-green-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setMode("request_changes")}
                          className="rounded border border-gray-400 px-3 py-1 text-sm disabled:opacity-50"
                        >
                          Request changes
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setMode("reject")}
                          className="rounded border border-red-400 px-3 py-1 text-sm text-red-700 disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    ) : (
                      <>
                        <label className="text-xs font-medium" htmlFor={`decision-${department}`}>
                          {mode === "reject" ? "Reason for rejecting (required)" : "Changes you request (required)"}
                        </label>
                        <textarea
                          id={`decision-${department}`}
                          value={text}
                          onChange={(event) => setText(event.target.value)}
                          rows={3}
                          className="rounded border border-gray-300 p-2 text-sm text-gray-900"
                        />
                        <div className="flex gap-2">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void handleDecision(department, mode)}
                            className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                          >
                            {busy ? "Sending..." : "Send"}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => {
                              setMode(null);
                              setText("");
                            }}
                            className="rounded border border-gray-400 px-3 py-1 text-sm"
                          >
                            Cancel
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}

                {pending && !mine && (
                  <p className="text-xs text-gray-500">
                    Only {pending.owner} can decide on this section.
                  </p>
                )}
              </article>
            );
          })}
        </div>
      )}

      {identity && !identity.actor && showBoard && (
        <p className="text-xs text-gray-500">Your account is not linked to a department approver (view only).</p>
      )}

      {ticket.status === "done" && (
        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void handleViewDocument()}
              className="w-fit rounded border border-gray-400 px-3 py-1 text-sm"
            >
              {finalDoc ? "Hide final document" : "View final document"}
            </button>
            {finalDoc && (
              <button
                type="button"
                onClick={handleDownload}
                className="w-fit rounded border border-gray-400 px-3 py-1 text-sm"
              >
                Download .md
              </button>
            )}
          </div>
          {finalDoc && (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-gray-300 bg-gray-50 p-3 text-xs text-gray-900">
              {finalDoc}
            </pre>
          )}
        </div>
      )}

      {showBoard && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => void handleToggleTrace()}
            className="w-fit rounded border border-gray-400 px-3 py-1 text-sm"
          >
            {trace ? "Hide execution trace" : "Show execution trace"}
          </button>
          {trace && (
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-gray-300">
                  <th className="py-1">Time (UTC)</th>
                  <th>Agent</th>
                  <th>Department</th>
                  <th>Input</th>
                  <th>Output</th>
                </tr>
              </thead>
              <tbody>
                {trace.map((event, index) => (
                  <tr key={`${event.ts}-${index}`} className="border-b border-gray-200">
                    <td className="py-1">{event.ts}</td>
                    <td>{event.agent}</td>
                    <td>{event.department ?? "-"}</td>
                    <td>{event.input_ref}</td>
                    <td>{event.output_ref}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
