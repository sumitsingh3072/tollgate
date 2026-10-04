// Minimal Server-Sent Events reader for OpenAI-style streams ("data: {...}" lines, "[DONE]" terminator).

export async function* readSSE<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const event = parseLine<T>(line);
        if (event === "done") return;
        if (event) yield event;
      }
    }
    const tail = parseLine<T>(buffer + decoder.decode());
    if (tail && tail !== "done") yield tail;
  } finally {
    reader.releaseLock();
  }
}

function parseLine<T>(line: string): T | "done" | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return null;
  const data = trimmed.slice(5).trim();
  if (data === "[DONE]") return "done";
  try {
    return JSON.parse(data) as T;
  } catch {
    return null;
  }
}
