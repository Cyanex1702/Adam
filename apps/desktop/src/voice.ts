import * as bridge from "./bridge";

export type Transcript = {
  raw_transcript: string;
  repaired_transcript: string;
  repair_applied: boolean;
  confidence: number;
  requires_review: boolean;
  language: string;
  interruption: string;
  partial: boolean;
  speaker_processing?: string;
  speaker?: { role: string; label?: string; confidence?: number };
  overlap?: boolean;
  replay_risk?: string;
  clarification?: string;
  utterances?: Array<{
    start: number;
    end: number;
    raw_transcript: string;
    overlap: boolean;
    speaker: { role: string; label?: string };
  }>;
};
export function automaticText(value: Transcript): boolean {
  return (
    !value.requires_review &&
    (!value.speaker_processing ||
      (value.speaker_processing === "COMPLETE" &&
        value.speaker?.role === "owner")) &&
    !value.overlap &&
    value.replay_risk !== "REPEATED_AUDIO" &&
    value.confidence >= 0.65 &&
    !!value.raw_transcript.trim() &&
    !value.raw_transcript.trim().startsWith("/")
  );
}
export function speechChunks(text: string, final = false): [string[], string] {
  const chunks: string[] = [];
  let rest = text;
  while (rest.length) {
    const match = rest.match(/^([\s\S]{12,200}?[.!?。؟۔](?:\s|$))/);
    let end = match
      ? match[0].length
      : rest.length >= 200
        ? rest.lastIndexOf(" ", 200)
        : 0;
    if (end < 1 && rest.length >= 200) end = 200;
    if (!end) break;
    chunks.push(rest.slice(0, end).trim());
    rest = rest.slice(end);
  }
  if (final && rest.trim()) {
    chunks.push(rest.trim());
    rest = "";
  }
  return [chunks.filter(Boolean), rest];
}
export function pcmBase64(samples: Float32Array): string {
  const bytes = new Uint8Array(samples.length * 2),
    view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i++)
    view.setInt16(
      i * 2,
      Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767),
      true,
    );
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192)
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(binary);
}
export class SpeechPlayer {
  sessionId: string | null = null;
  generation = 0;
  queue: string[] = [];
  rest = "";
  enabled = false;
  language = "en-us";
  engine = "configured";
  context: AudioContext | null = null;
  source: AudioBufferSourceNode | null = null;
  playing = false;
  running = false;
  onState: (playing: boolean, energy: number) => void = () => {};
  onError: (error: unknown) => void = () => {};
  onNotice: (notice: string) => void = () => {};
  async unlock() {
    this.context ??= new AudioContext();
    await this.context.resume();
  }
  append(text: string, final = false) {
    if (!this.enabled) return;
    const [chunks, rest] = speechChunks(this.rest + text, final);
    this.rest = rest;
    if (this.queue.length + chunks.length > 32) {
      this.stop();
      this.onError("VOICE.OUTPUT_LIMIT");
      return;
    }
    this.queue.push(...chunks);
    void this.pump();
  }
  stop() {
    this.generation++;
    this.queue = [];
    this.rest = "";
    this.source?.stop();
    this.source = null;
    this.playing = false;
    this.onState(false, 0);
  }
  async close() {
    this.stop();
    const context = this.context;
    this.context = null;
    await context?.close();
  }
  private async pump() {
    if (this.running) return;
    this.running = true;
    try {
      while (this.queue.length && this.enabled) {
        const generation = this.generation,
          text = this.queue.shift()!;
        const audio = await bridge.api<{
          pcm16: string;
          sample_rate: number;
          slower_than_realtime?: boolean;
        }>("/voice/speak", {
          session_id: this.sessionId,
          text,
          language: this.language,
          engine: this.engine,
        });
        if (generation !== this.generation || !this.enabled || !this.context)
          continue;
        if (audio.slower_than_realtime)
          this.onNotice(
            "Speech synthesis is slower than playback on this PC right now. Text remains available.",
          );
        const binary = atob(audio.pcm16),
          bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
        if (
          bytes.length > 24000 * 2 * 45 ||
          bytes.length % 2 ||
          audio.sample_rate !== 24000
        )
          throw "VOICE.INVALID_AUDIO";
        const view = new DataView(bytes.buffer);
        const buffer = this.context.createBuffer(
          1,
          bytes.length / 2,
          audio.sample_rate,
        );
        const samples = buffer.getChannelData(0);
        for (let i = 0; i < samples.length; i++)
          samples[i] = view.getInt16(i * 2, true) / 32768;
        const source = this.context.createBufferSource();
        this.source = source;
        source.buffer = buffer;
        source.connect(this.context.destination);
        this.playing = true;
        await new Promise<void>((resolve) => {
          const started = performance.now();
          const meter = setInterval(() => {
            const offset = Math.floor(
              ((performance.now() - started) / 1000) * audio.sample_rate,
            );
            let energy = 0,
              count = 0;
            for (
              let i = offset;
              i < Math.min(offset + 1200, samples.length);
              i++
            ) {
              energy += samples[i] ** 2;
              count++;
            }
            this.onState(true, Math.sqrt(energy / Math.max(1, count)));
          }, 80);
          source.onended = () => {
            clearInterval(meter);
            source.disconnect();
            resolve();
          };
          source.start();
        });
        if (generation === this.generation) {
          this.source = null;
          this.playing = false;
          this.onState(false, 0);
        }
      }
    } catch (error) {
      this.stop();
      this.onError(error);
    } finally {
      this.running = false;
      if (this.queue.length) void this.pump();
    }
  }
}

export class Microphone {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  async start(onFrame: (samples: Float32Array) => void) {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      this.context = new AudioContext({ sampleRate: 16000 });
      if (this.context.sampleRate !== 16000)
        throw "VOICE.SAMPLE_RATE_UNSUPPORTED";
      await this.context.resume();
      this.source = this.context.createMediaStreamSource(this.stream);
      // Fixed 128 ms PCM frames. No encoder downloads, worklet blobs, or disk audio.
      this.processor = this.context.createScriptProcessor(2048, 1, 1);
      this.processor.onaudioprocess = (event) =>
        onFrame(event.inputBuffer.getChannelData(0).slice());
      this.source.connect(this.processor);
      this.processor.connect(this.context.destination); // Output buffer remains zero.
    } catch (error) {
      this.stop();
      throw error;
    }
  }
  stop() {
    if (this.processor) {
      this.processor.onaudioprocess = null;
      this.processor.disconnect();
    }
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.context?.close();
    this.context = null;
    this.stream = null;
    this.processor = null;
    this.source = null;
  }
}
