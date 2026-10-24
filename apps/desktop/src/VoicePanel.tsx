import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import * as bridge from "./bridge";
import { friendlyError } from "./state";
import { SpeakerPanel } from "./SpeakerPanel";
import {
  automaticText,
  Microphone,
  pcmBase64,
  SpeechPlayer,
  type Transcript,
} from "./voice";

export type VoiceHandle = {
  begin: () => void;
  append: (text: string, final?: boolean) => void;
  reset: () => void;
  session: (id: string) => void;
};
type Props = {
  sessionId: string | null;
  busy: boolean;
  onSend: (text: string) => Promise<void>;
  onInterrupt: () => Promise<void>;
  onActivity: (
    state: "LISTENING" | "SPEAKING" | "IDLE",
    energy: number,
  ) => void;
};
export const VoicePanel = forwardRef<VoiceHandle, Props>(
  function VoicePanel(props, ref) {
    const [status, setStatus] = useState<any>(null),
      [notice, setNotice] = useState("");
    const [recording, setRecording] = useState(false),
      [processing, setProcessing] = useState(false);
    const [continuous, setContinuous] = useState(false),
      [readAloud, setReadAloud] = useState(false);
    const [recognition, setRecognition] = useState("auto"),
      [language, setLanguage] = useState("en-us");
    const [engine, setEngine] = useState("configured");
    const [enrolling, setEnrolling] = useState(false);
    const actualEngine =
      engine === "configured" ? status?.default_tts_engine : engine;
    const ttsReady =
      actualEngine === "windows" ? status?.windows_ready : status?.kokoro_ready;
    const [transcript, setTranscript] = useState<Transcript | null>(null),
      [edited, setEdited] = useState("");
    const [speaking, setSpeaking] = useState(false),
      [level, setLevel] = useState(0);
    const microphone = useRef(new Microphone()),
      player = useRef(new SpeechPlayer());
    const latest = useRef(props),
      generation = useRef(0),
      enabled = useRef(false),
      automatic = useRef(false);
    const frames = useRef<Float32Array[]>([]),
      size = useRef(0),
      lastSpeech = useRef(0),
      lastInference = useRef(0);
    const inference = useRef(false),
      voiceFrames = useRef(0),
      noise = useRef(0.003),
      selectedLanguage = useRef(recognition);
    const completed = useRef(false),
      decisionBusy = useRef(false),
      currentTranscript = useRef<Transcript | null>(null);
    const starting = useRef(false);
    latest.current = props;
    automatic.current = continuous;
    selectedLanguage.current = recognition;
    player.current.enabled = readAloud;
    player.current.language = language;
    player.current.engine = engine;
    player.current.sessionId = props.sessionId;
    player.current.onState = (active, energy) => {
      setSpeaking(active);
      latest.current.onActivity(
        active ? "SPEAKING" : enabled.current ? "LISTENING" : "IDLE",
        energy,
      );
    };
    player.current.onError = (error) => setNotice(friendlyError(error));
    player.current.onNotice = (message) => setNotice(message);
    useEffect(() => {
      if (!props.sessionId) return;
      let active = true;
      const timer = setInterval(() => {
        void bridge.api<{primary:string}>("/mesh/session-state", {session_id:props.sessionId,primary:"desktop"})
          .then(state => { if (active && state.primary !== "desktop") player.current.stop(); })
          .catch(() => { /* Mesh may be disabled; synthesis still checks ownership. */ });
      }, 1000);
      return () => { active = false; clearInterval(timer); };
    }, [props.sessionId]);
    function discard() {
      frames.current = [];
      size.current = 0;
      voiceFrames.current = 0;
      lastSpeech.current = 0;
      currentTranscript.current = null;
      completed.current = false;
    }
    function stopMicrophone() {
      enabled.current = false;
      generation.current++;
      microphone.current.stop();
      setRecording(false);
      setLevel(0);
      discard();
      setProcessing(false);
      latest.current.onActivity(
        player.current.playing ? "SPEAKING" : "IDLE",
        0,
      );
    }
    function reset() {
      stopMicrophone();
      player.current.enabled = false;
      void player.current.close();
      setReadAloud(false);
      setContinuous(false);
      setTranscript(null);
      setEdited("");
      setNotice("");
    }
    useImperativeHandle(ref, () => ({
      begin: () => player.current.stop(),
      append: (text, final = false) => player.current.append(text, final),
      reset,
      session: (id) => { player.current.sessionId = id; },
    }));
    useEffect(() => {
      let mounted = true;
      bridge
        .api("/voice/status")
        .then((value) => {
          if (mounted) setStatus(value);
        })
        .catch((error) => {
          if (mounted) setNotice(friendlyError(error));
        });
      const hidden = () => {
        if (document.hidden) {
          reset();
          player.current.stop();
        }
      };
      document.addEventListener("visibilitychange", hidden);
      return () => {
        mounted = false;
        generation.current++;
        enabled.current = false;
        microphone.current.stop();
        void player.current.close();
        document.removeEventListener("visibilitychange", hidden);
      };
    }, []);
    async function accept(value: Transcript, manual = false) {
      if (!(manual ? edited : value.raw_transcript).trim()) return;
      if (!manual && !automaticText(value)) {
        setNotice(
          "Review the transcript before sending. Speech confidence is only an estimate.",
        );
        return;
      }
      if (player.current.playing || latest.current.busy) {
        if (value.interruption === "ACKNOWLEDGEMENT") {
          discard();
          return;
        }
        if (value.interruption === "HARD_INTERRUPT") {
          player.current.stop();
          await latest.current.onInterrupt();
          discard();
          setNotice("Stopped.");
          return;
        }
        player.current.stop();
        await latest.current.onInterrupt();
      }
      const text = manual ? edited.trim() : value.raw_transcript;
      discard();
      setTranscript(null);
      setEdited("");
      await latest.current.onSend(text);
    }
    async function transcribe(final: boolean) {
      if (inference.current || !size.current || size.current < 3200) return;
      const expected = generation.current,
        speechAt = lastSpeech.current;
      const audio = new Float32Array(size.current);
      let offset = 0;
      for (const frame of frames.current) {
        audio.set(frame, offset);
        offset += frame.length;
      }
      inference.current = true;
      setProcessing(true);
      lastInference.current = performance.now();
      try {
        const value = await bridge.api<Transcript>("/voice/transcribe", {
          pcm16: pcmBase64(audio),
          sample_rate: 16000,
          language: selectedLanguage.current,
          partial: !final,
          mode: automatic.current ? "conversation" : "push_to_talk",
          silence_ms: Math.min(30000, Math.round(performance.now() - speechAt)),
        });
        if (expected !== generation.current) return;
        currentTranscript.current = value;
        setTranscript(value);
        setEdited(value.raw_transcript);
        if (!value.raw_transcript) {
          if (final)
            setNotice(
              value.clarification ||
                "No speech was detected. Try again or type your message.",
            );
          return;
        }
        if (player.current.playing || latest.current.busy) {
          if (value.interruption === "HARD_INTERRUPT" && automaticText(value)) {
            player.current.stop();
            await latest.current.onInterrupt();
            discard();
            setNotice("Stopped.");
            return;
          }
          if (value.interruption === "ACKNOWLEDGEMENT") {
            discard();
            return;
          }
          if (value.interruption === "CORRECTION" && automaticText(value)) {
            player.current.stop();
            await latest.current.onInterrupt();
          }
        }
        if (final) {
          setNotice("Review your words, then send.");
        }
      } catch (error) {
        if (expected === generation.current) {
          setNotice(friendlyError(error));
          stopMicrophone();
        }
      } finally {
        inference.current = false;
        if (expected === generation.current) setProcessing(false);
      }
    }
    async function decide(now: number) {
      const value = currentTranscript.current;
      if (
        !automatic.current ||
        !enabled.current ||
        !value ||
        decisionBusy.current ||
        inference.current ||
        completed.current
      )
        return;
      if (now - lastSpeech.current < 800 || now - lastInference.current < 250)
        return;
      const expected = generation.current,
        speechAt = lastSpeech.current;
      decisionBusy.current = true;
      try {
        const decision = await bridge.api<any>("/voice/turn", {
          text: value.raw_transcript,
          confidence: value.confidence,
          silence_ms: Math.min(30000, Math.round(now - speechAt)),
          speech_active: false,
        });
        if (expected !== generation.current || speechAt !== lastSpeech.current)
          return;
        if (
          decision.recommended_action === "TAKE_TURN" &&
          (automaticText(value) || (value.partial && value.confidence >= 0.65))
        ) {
          completed.current = true;
          // Re-decode the full utterance; a speculative partial is never dispatched.
          await transcribe(true);
          const final = currentTranscript.current;
          if (
            expected === generation.current &&
            speechAt === lastSpeech.current &&
            final &&
            !final.partial
          )
            await accept(final);
          else completed.current = false;
        } else if (value.requires_review)
          setNotice("Low-confidence speech: review and send, or record again.");
      } catch (error) {
        if (expected === generation.current) setNotice(friendlyError(error));
      } finally {
        decisionBusy.current = false;
      }
    }
    async function startMicrophone() {
      if (
        document.hidden ||
        recording ||
        starting.current ||
        !status?.stt_ready ||
        !status?.enabled
      )
        return;
      starting.current = true;
      const expected = ++generation.current;
      setNotice("");
      setTranscript(null);
      setEdited("");
      discard();
      try {
        await player.current.unlock();
        await microphone.current.start((frame) => {
          if (!enabled.current) return;
          const now = performance.now();
          const rms = Math.sqrt(
            frame.reduce((sum, value) => sum + value * value, 0) / frame.length,
          );
          setLevel(Math.min(1, rms * 8));
          const threshold = Math.max(
            player.current.playing ? 0.025 : 0.008,
            noise.current * 3,
          );
          const active = rms > threshold;
          if (!active && !size.current)
            noise.current = Math.min(0.02, noise.current * 0.98 + rms * 0.02);
          if (active) {
            const pause = now - lastSpeech.current;
            if (
              lastSpeech.current &&
              pause >= 600 &&
              pause <= 5000 &&
              voiceFrames.current > 1
            )
              void bridge
                .api("/voice/turn", {
                  text: "",
                  confidence: 1,
                  silence_ms: 0,
                  speech_active: true,
                  observed_pause_ms: Math.round(pause),
                })
                .catch(() => {});
            lastSpeech.current = now;
            voiceFrames.current++;
          }
          if (voiceFrames.current || !automatic.current) {
            frames.current.push(frame);
            size.current += frame.length;
          }
          if (size.current >= 16000 * 58) {
            // Explicit review at the duration bound; never truncate into an auto command.
            void finishMicrophone();
            return;
          }
          const cadence =
            player.current.playing || latest.current.busy ? 450 : 1500;
          if (
            automatic.current &&
            voiceFrames.current >= 2 &&
            now - lastInference.current > cadence &&
            !inference.current
          )
            void transcribe(false);
          if (automatic.current) void decide(now);
        });
        if (expected !== generation.current) {
          microphone.current.stop();
          return;
        }
        enabled.current = true;
        setRecording(true);
        latest.current.onActivity("LISTENING", 0);
      } catch (error) {
        stopMicrophone();
        setNotice(
          error instanceof DOMException
            ? "Microphone unavailable or permission denied. Check Windows microphone access, or use text."
            : friendlyError(error),
        );
      } finally {
        starting.current = false;
      }
    }
    async function finishMicrophone() {
      const expected = generation.current;
      enabled.current = false;
      microphone.current.stop();
      setRecording(false);
      setLevel(0);
      latest.current.onActivity("IDLE", 0);
      // Wait for the single partial request to drain before final decoding.
      while (inference.current)
        await new Promise((resolve) => setTimeout(resolve, 50));
      if (expected !== generation.current) return;
      await transcribe(true);
      frames.current = [];
      size.current = 0;
    }
    return (
      <section className="voice-panel" aria-label="Local voice controls">
        <div className="voice-controls">
          <button
            type="button"
            className={recording ? "secondary recording" : "secondary"}
            disabled={
              !status?.enabled ||
              !status?.stt_ready ||
              enrolling ||
              (processing && !recording)
            }
            onClick={() =>
              void (recording ? finishMicrophone() : startMicrophone())
            }
          >
            {recording ? "Finish recording" : "Record voice"}
          </button>
          <label>
            <input
              type="checkbox"
              checked={continuous}
              disabled={recording}
              onChange={(e) => setContinuous(e.target.checked)}
            />{" "}
            Conversation mode
          </label>
          <label>
            <input
              type="checkbox"
              checked={readAloud}
              disabled={!ttsReady || !status?.enabled}
              onChange={(e) => {
                setReadAloud(e.target.checked);
                if (e.target.checked)
                  void player.current
                    .unlock()
                    .catch((error) => setNotice(friendlyError(error)));
                else player.current.stop();
              }}
            />{" "}
            Read replies aloud
          </label>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              player.current.stop();
              void latest.current.onInterrupt();
            }}
            aria-label="Stop voice and response"
          >
            Stop
          </button>
        </div>
        <details>
          <summary>Voice settings</summary>
          <div className="voice-options">
            <label>
              Speech engine{" "}
              <select
                aria-label="Speech engine"
                value={engine}
                disabled={speaking || readAloud}
                onChange={(e) => {
                  setEngine(e.target.value);
                  setLanguage("en-us");
                }}
              >
                <option value="configured">
                  Default ({status?.default_tts_engine ?? "local"})
                </option>
                <option value="windows" disabled={!status?.windows_ready}>
                  Windows offline · English
                </option>
                <option value="kokoro" disabled={!status?.kokoro_ready}>
                  Kokoro · multilingual
                </option>
              </select>
            </label>
            <label>
              Recognition{" "}
              <select
                aria-label="Recognition language"
                value={recognition}
                disabled={recording}
                onChange={(e) => setRecognition(e.target.value)}
              >
                {["auto", "en", "ur", "hi", "es", "fr", "de", "ja", "zh"].map(
                  (value) => (
                    <option key={value}>{value}</option>
                  ),
                )}
              </select>
            </label>
            <label>
              Speaking{" "}
              <select
                aria-label="Speaking language"
                value={language}
                disabled={speaking}
                onChange={(e) => setLanguage(e.target.value)}
              >
                {(actualEngine === "windows"
                  ? ["en-us", "en-gb"]
                  : ["en-us", "en-gb", "fr-fr", "es", "it", "pt-br", "hi"]
                ).map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                void bridge
                  .api("/voice/turn", {
                    text: "",
                    confidence: 1,
                    silence_ms: 0,
                    reset_profile: true,
                  })
                  .then(() => setNotice("Pause learning reset."))
                  .catch((error) => setNotice(friendlyError(error)))
              }
            >
              Reset pause style
            </button>
          </div>
          <small>
            Conversation mode sends confident speech after pauses. Urdu
            recognition is available; Urdu speech output is not. Raw and edited
            transcripts are shown separately.
          </small>
        </details>
        {status?.speaker_enabled && (
          <SpeakerPanel
            disabled={recording || processing || props.busy}
            onRecording={setEnrolling}
          />
        )}
        <p className="voice-status" role="status">
          {recording
            ? `Microphone on${continuous ? " · conversation mode" : " · press Finish to review"}`
            : processing
              ? "Transcribing locally…"
              : speaking
                ? `Speaking locally · ${actualEngine === "windows" ? "Windows" : "Kokoro"}`
                : "Microphone off"}
          {recording && (
            <meter
              aria-label="Microphone level"
              min={0}
              max={1}
              value={level}
            />
          )}
        </p>
        {transcript && (
          <div className="transcript-review">
            {transcript.speaker_processing && (
              <p>
                Speaker:{" "}
                {transcript.speaker?.label ||
                  transcript.speaker?.role ||
                  "unknown"}{" "}
                · advisory match only.{" "}
                {transcript.replay_risk === "REPEATED_AUDIO"
                  ? "Repeated audio detected; review required."
                  : "Recording or cloned voice cannot be ruled out."}{" "}
                {transcript.clarification}
              </p>
            )}
            {transcript.utterances?.map((u, i) => (
              <p key={i}>
                {u.start.toFixed(1)}–{u.end.toFixed(1)}s ·{" "}
                {u.speaker.label || u.speaker.role}:{" "}
                {u.overlap
                  ? "Overlapping voices; please repeat one at a time."
                  : u.raw_transcript}{" "}
                {!u.overlap && u.raw_transcript && (
                  <button
                    type="button"
                    onClick={() => setEdited(u.raw_transcript)}
                  >
                    Review this speaker's words
                  </button>
                )}
              </p>
            ))}
            <label>
              Transcript{" "}
              {transcript.partial ? "(partial)" : "(review before sending)"} ·
              estimated confidence {Math.round(transcript.confidence * 100)}% ·{" "}
              {transcript.language}
              <textarea
                aria-label="Voice transcript"
                value={edited}
                maxLength={4000}
                onChange={(e) => setEdited(e.target.value)}
              />
            </label>
            <small>
              Raw: {transcript.raw_transcript || "No speech detected"}. No
              transcript repair applied.
            </small>
            <button
              type="button"
              className="secondary"
              disabled={!edited.trim() || props.busy || processing || recording}
              onClick={() => void accept(transcript, true)}
            >
              Send reviewed transcript
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                stopMicrophone();
                setTranscript(null);
                setEdited("");
              }}
            >
              Discard
            </button>
          </div>
        )}
        {notice && (
          <p className="voice-notice" role="status">
            {notice}
          </p>
        )}
        {status && !status.stt_ready && (
          <p>
            Voice assets are missing. Run scripts/setup-voice.ps1; text remains
            available.
          </p>
        )}
        <small>
          Local processing ·{" "}
          {status?.raw_audio_retention
            ? "Audio retention enabled in configuration"
            : "Raw audio is not retained"}{" "}
          · headphones recommended.
        </small>
      </section>
    );
  },
);
