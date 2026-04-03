/**
 * SSE stream parser for aiops-agent events.
 * Parses `data: {...}` lines and calls onEvent for each parsed event.
 */
export async function consumeSSE(
  response: Response,
  onEvent: (event: Record<string, unknown>) => void,
  onError?: (err: Error) => void
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === "[DONE]") continue;
        try {
          onEvent(JSON.parse(raw));
        } catch {
          // skip malformed lines
        }
      }
    }
  } catch (err) {
    onError?.(err instanceof Error ? err : new Error(String(err)));
  } finally {
    reader.releaseLock();
  }
}
