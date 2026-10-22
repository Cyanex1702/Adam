import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { AgentEvent } from "./state";
export const native = "__TAURI_INTERNALS__" in window;
const browserQA =
  import.meta.env.DEV && import.meta.env.VITE_ADAM_BROWSER_QA === "1";
export async function start(restart = false) {
  if (native) return invoke("backend_start", { restart });
  if (!browserQA) throw "DESKTOP.NATIVE_REQUIRED";
}
export async function api<T = any>(path: string, body?: unknown): Promise<T> {
  if (native)
    return invoke<T>("api_request", {
      method: body === undefined ? "GET" : "POST",
      path,
      body: body ?? null,
    });
  if (!browserQA) throw "DESKTOP.NATIVE_REQUIRED";
  const response = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "include",
    cache: "no-store",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw result.error ?? "DESKTOP.REQUEST_FAILED";
  if (result && typeof result === "object") delete result.token;
  return result;
}
let browserCancel: AbortController | null = null;
export async function send(
  requestId: string,
  body: unknown,
  onEvent: (event: AgentEvent) => void,
) {
  if (native) {
    const unlisten = await listen<{ request_id: string; event: AgentEvent }>(
      "adam:event",
      (message) => {
        if (message.payload.request_id === requestId)
          onEvent(message.payload.event);
      },
    );
    try {
      return await invoke<{ cancelled?: boolean }>("chat", { requestId, body });
    } finally {
      unlisten();
    }
  }
  if (!browserQA) throw "DESKTOP.NATIVE_REQUIRED";
  const controller = new AbortController();
  browserCancel = controller;
  try {
    const response = await fetch("/api/desktop/chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) throw "DESKTOP.CHAT_DENIED";
    const reader = response.body!.getReader(),
      decoder = new TextDecoder();
    let buffer = "",
      terminal = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > 1024 * 1024) throw "DESKTOP.RESPONSE_LIMIT";
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const event = JSON.parse(buffer.slice(0, index));
        buffer = buffer.slice(index + 1);
        onEvent(event);
        if (["agent.completed", "agent.error"].includes(event.event_type))
          terminal = true;
      }
    }
    if (!terminal || buffer.length) throw "DESKTOP.STREAM_INTERRUPTED";
    return {};
  } catch (error) {
    if (controller.signal.aborted) return { cancelled: true };
    throw error;
  } finally {
    browserCancel = null;
  }
}
export async function cancel() {
  if (native) await invoke("cancel_chat");
  else browserCancel?.abort();
}

export async function applyRelease(ticket: string, token: string) {
  if (!native) throw "DESKTOP.NATIVE_REQUIRED";
  return invoke("apply_release", { ticket, token });
}
