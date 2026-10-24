import { describe, expect, it, vi } from "vitest";
vi.mock("./bridge", () => ({ api: vi.fn() }));
import * as bridge from "./bridge";
import {
  automaticText,
  Microphone,
  pcmBase64,
  SpeechPlayer,
  speechChunks,
  type Transcript,
} from "./voice";

it("stops a late microphone grant after the window was hidden", async () => {
  let grant!: (stream: MediaStream) => void;
  const track = { stop: vi.fn() };
  const createAudio = vi.fn();
  vi.stubGlobal("navigator", {mediaDevices: {getUserMedia: () => new Promise<MediaStream>(resolve => {grant = resolve;})}});
  vi.stubGlobal("AudioContext", createAudio);
  try {
    const microphone = new Microphone();
    const starting = microphone.start(vi.fn());
    microphone.stop();
    grant({getTracks: () => [track]} as unknown as MediaStream);
    await starting;
    expect(track.stop).toHaveBeenCalledOnce();
    expect(createAudio).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});

describe("voice input and bounded sentence output", () => {
  const value: Transcript = {
    raw_transcript: "Hello there.",
    repaired_transcript: "Hello there.",
    repair_applied: false,
    confidence: 0.9,
    requires_review: false,
    language: "en",
    interruption: "NEW_REQUEST",
    partial: false,
  };
  it("never auto dispatches low confidence or slash commands", () => {
    expect(automaticText(value)).toBe(true);
    expect(automaticText({ ...value, confidence: 0.2 })).toBe(false);
    expect(automaticText({ ...value, requires_review: true })).toBe(false);
    expect(
      automaticText({ ...value, raw_transcript: " /forget everything" }),
    ).toBe(false);
  });
  it("preserves streamed words, bounded phrases, and a final tail", () => {
    const text = "This is a sentence. " + "a ".repeat(250) + "tail";
    const [chunks, rest] = speechChunks(text);
    expect(chunks.every((c) => c.length <= 240)).toBe(true);
    const [last, tail] = speechChunks(rest, true);
    expect(tail).toBe("");
    expect([...chunks, ...last].join(" ").replace(/\s+/g, " ").trim()).toBe(
      text.replace(/\s+/g, " ").trim(),
    );
  });
  it("requires a completed owner match and rejects replay and overlap", () => {
    const owner = {
      ...value,
      speaker_processing: "COMPLETE",
      speaker: { role: "owner" },
    };
    expect(automaticText(owner)).toBe(true);
    for (const role of ["unknown", "guest"])
      expect(automaticText({ ...owner, speaker: { role } })).toBe(false);
    expect(
      automaticText({ ...owner, speaker_processing: "FINAL_REQUIRED" }),
    ).toBe(false);
    expect(automaticText({ ...owner, overlap: true })).toBe(false);
    expect(automaticText({ ...owner, replay_risk: "REPEATED_AUDIO" })).toBe(
      false,
    );
  });
  it("encodes signed little endian PCM and clips amplitude", () => {
    const result = atob(pcmBase64(new Float32Array([-2, 0, 2])));
    const bytes = Uint8Array.from(result, (c) => c.charCodeAt(0));
    const view = new DataView(bytes.buffer);
    expect(view.getInt16(0, true)).toBe(-32767);
    expect(view.getInt16(2, true)).toBe(0);
    expect(view.getInt16(4, true)).toBe(32767);
  });
  it("stop invalidates in-flight synthesis and clears all queued audio", async () => {
    let resolve: (value: unknown) => void = () => {};
    vi.mocked(bridge.api).mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const player = new SpeechPlayer();
    player.enabled = true;
    player.append("This is a first sentence. This is a second sentence.", true);
    expect(player.running).toBe(true);
    player.stop();
    expect(player.queue).toEqual([]);
    expect(player.rest).toBe("");
    resolve({ pcm16: "", sample_rate: 24000 });
    await new Promise((done) => setTimeout(done, 0));
    expect(player.playing).toBe(false);
    expect(player.running).toBe(false);
  });
});
