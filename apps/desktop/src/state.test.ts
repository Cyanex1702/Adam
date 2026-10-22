import { describe, it, expect } from "vitest";
import { visualState, readPreferences, friendlyError } from "./state";
describe("operational avatar events", () => {
  it("keeps deterministic memory distinct from model and tool activity", () => {
    expect(
      visualState("IDLE", {
        kind: "backend",
        event: { event_type: "agent.started", payload: { state: "MEMORY" } },
      }),
    ).toBe("UNDERSTANDING");
    expect(
      visualState("IDLE", {
        kind: "backend",
        event: { event_type: "tool.started", payload: {} },
      }),
    ).toBe("USING_TOOL");
    expect(
      visualState("USING_TOOL", {
        kind: "backend",
        event: { event_type: "tool.completed", payload: {} },
      }),
    ).toBe("IDLE");
    expect(visualState("ERROR", { kind: "connection", online: true })).toBe(
      "ERROR",
    );
  });
  it("uses real activity and preserves unknown event state", () => {
    expect(visualState("IDLE", { kind: "request" })).toBe("UNDERSTANDING");
    expect(
      visualState("IDLE", {
        kind: "backend",
        event: {
          event_type: "agent.started",
          payload: { state: "RETRIEVING" },
        },
      }),
    ).toBe("SEARCHING");
    expect(
      visualState("IDLE", {
        kind: "backend",
        event: { event_type: "agent.started", payload: { state: "THINKING" } },
      }),
    ).toBe("THINKING");
    expect(
      visualState("THINKING", {
        kind: "backend",
        event: { event_type: "voice.listening", payload: {} },
      }),
    ).toBe("THINKING");
  });
  it("surfaces uncertainty, failures, offline and explicit permission", () => {
    expect(
      visualState("THINKING", {
        kind: "backend",
        event: {
          event_type: "agent.completed",
          payload: { epistemic_status: "UNCERTAIN" },
        },
      }),
    ).toBe("UNCERTAIN");
    expect(
      visualState("THINKING", {
        kind: "backend",
        event: { event_type: "agent.error", payload: {} },
      }),
    ).toBe("ERROR");
    expect(
      visualState("IDLE", {
        kind: "backend",
        event: { event_type: "approval.required", payload: {} },
      }),
    ).toBe("WAITING_FOR_PERMISSION");
    expect(visualState("THINKING", { kind: "connection", online: false })).toBe(
      "OFFLINE",
    );
    expect(visualState("THINKING", { kind: "cancel" })).toBe("IDLE");
  });
});
it("bounds persisted preferences to UI booleans", () => {
  expect(readPreferences("broken", true)).toEqual({
    avatar: true,
    reducedMotion: true,
  });
  expect(
    readPreferences(
      '{"avatar":"false","reducedMotion":false,"token":"ignored"}',
      true,
    ),
  ).toEqual({ avatar: true, reducedMotion: false });
});
it("does not display raw error content or secrets", () => {
  expect(friendlyError("private path and password")).toBe(
    "The operation could not finish. Try again.",
  );
  expect(friendlyError("RESOURCE.PRESSURE")).toContain("free resources");
});
