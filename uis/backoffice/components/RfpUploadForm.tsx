"use client";

import { useRef, useState } from "react";
import { uploadRfp } from "@/lib/rfp";

export default function RfpUploadForm({
  onUploaded,
}: {
  onUploaded: (ticketId: number) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a PDF first.");
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const { ticket_id } = await uploadRfp(file);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      onUploaded(ticket_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border border-gray-300 p-4 sm:flex-row sm:items-center"
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        className="flex-1 text-sm"
        aria-label="RFP PDF file"
      />
      <button
        type="submit"
        disabled={uploading || !file}
        className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {uploading ? "Uploading..." : "Upload RFP"}
      </button>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </form>
  );
}
