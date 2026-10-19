// lib/sseParser.ts
//
// Incremental parser for the Server-Sent Events wire format. It is fed the decoded text of
// each network chunk and returns the complete frames found so far. A chunk can end in the
// middle of a line or a frame, so the unfinished tail is kept in a buffer until the next read.
//
//   id: 12
//   event: rfp_ticket_created
//   data: {"id": 4}
//   <blank line>            <- ends the frame
//
// Lines starting with ":" are comments (": connected", ": keepalive") and are ignored.
// No imports on purpose: this file is plain logic that can be tested without the app.

export interface SseFrame {
  // null when the frame carried no `id:` field.
  id: string | null;
  // "message" when the frame carried no `event:` field (the SSE default).
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";
  private id: string | null = null;
  private event = "";
  private data: string[] = [];

  feed(chunk: string): SseFrame[] {
    this.buffer += chunk;

    // A lone "\r" at the end of a chunk may be the first half of "\r\n": hold it back.
    let text = this.buffer;
    let tail = "";
    if (text.endsWith("\r")) {
      tail = "\r";
      text = text.slice(0, -1);
    }
    text = text.replace(/\r\n|\r/g, "\n");

    const lastNewline = text.lastIndexOf("\n");
    if (lastNewline === -1) {
      this.buffer = text + tail;
      return [];
    }

    const completeLines = text.slice(0, lastNewline).split("\n");
    this.buffer = text.slice(lastNewline + 1) + tail;

    const frames: SseFrame[] = [];
    for (const line of completeLines) {
      const frame = this.consumeLine(line);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  private consumeLine(line: string): SseFrame | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "id") {
      // Per the spec an id containing NUL is ignored.
      if (!value.includes("\0")) this.id = value;
    } else if (field === "event") {
      this.event = value;
    } else if (field === "data") {
      this.data.push(value);
    }
    // "retry" and unknown fields are ignored.
    return null;
  }

  private dispatch(): SseFrame | null {
    const frame: SseFrame | null =
      this.data.length > 0 ? { id: this.id, event: this.event || "message", data: this.data.join("\n") } : null;
    // A frame without data is not delivered (the spec drops it), but its fields are reset.
    this.id = null;
    this.event = "";
    this.data = [];
    return frame;
  }
}
