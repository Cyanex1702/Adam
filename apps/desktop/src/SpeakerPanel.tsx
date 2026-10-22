import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";
import { friendlyError } from "./state";
import { Microphone, pcmBase64 } from "./voice";

type Speaker = { speaker_id: string; label: string; role: string };
export function SpeakerPanel({
  disabled,
  onRecording,
}: {
  disabled: boolean;
  onRecording: (value: boolean) => void;
}) {
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [label, setLabel] = useState("");
  const [role, setRole] = useState("owner");
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const mic = useRef(new Microphone());
  const frames = useRef<Float32Array[]>([]);
  const size = useRef(0);
  const generation = useRef(0);
  function stop() {
    generation.current++;
    mic.current.stop();
    frames.current = [];
    size.current = 0;
    setRecording(false);
    onRecording(false);
  }
  async function refresh() {
    setSpeakers(await bridge.api<Speaker[]>("/voice/speakers"));
  }
  useEffect(() => {
    void refresh().catch((e) => setNotice(friendlyError(e)));
    const hidden = () => {
      if (document.hidden) stop();
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      generation.current++;
      mic.current.stop();
      onRecording(false);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  async function finish() {
    mic.current.stop();
    setRecording(false);
    onRecording(false);
    const audio = new Float32Array(Math.min(size.current, 16000 * 20));
    let offset = 0;
    for (const frame of frames.current) {
      const clipped = frame.subarray(0, audio.length - offset);
      audio.set(clipped, offset);
      offset += clipped.length;
      if (offset === audio.length) break;
    }
    frames.current = [];
    size.current = 0;
    const expected = generation.current;
    setBusy(true);
    try {
      await bridge.api("/developer/voice/enroll", {
        pcm16: pcmBase64(audio),
        sample_rate: 16000,
        label,
        role,
        consent: true,
      });
      if (expected !== generation.current) return;
      setNotice("Voice template saved. Voice matches do not authenticate you.");
      setConsent(false);
      await refresh();
    } catch (e) {
      if (expected === generation.current) setNotice(friendlyError(e));
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    setBusy(true);
    const expected = ++generation.current;
    setNotice(
      "Read continuously for 6–20 seconds, alone in a quiet room, then finish.",
    );
    frames.current = [];
    size.current = 0;
    onRecording(true);
    try {
      await mic.current.start((frame) => {
        if (expected !== generation.current) return;
        frames.current.push(frame);
        size.current += frame.length;
        if (size.current >= 16000 * 20) void finish();
      });
      if (expected !== generation.current) {
        mic.current.stop();
        return;
      }
      setRecording(true);
    } catch (e) {
      stop();
      setNotice(friendlyError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details>
      <summary>Speaker recognition and enrollment</summary>
      <p>
        Matches are advisory and can be fooled by recordings or cloned voices.
        Unknown voices, guests and overlapping speech require review. Spatial
        audio is deferred for this mono microphone.
      </p>
      <p>
        To enroll or remove a template, unlock Developer view with your owner
        password first. Templates are encrypted for this Windows account and
        profile; recordings are discarded.
      </p>
      <label>
        Speaker label{" "}
        <input
          aria-label="Speaker label"
          maxLength={48}
          value={label}
          disabled={recording || busy}
          onChange={(e) => setLabel(e.target.value)}
        />
      </label>
      <label>
        Speaker role{" "}
        <select
          aria-label="Speaker role"
          value={role}
          disabled={recording || busy}
          onChange={(e) => setRole(e.target.value)}
        >
          <option value="owner">Owner</option>
          <option value="guest">Guest</option>
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={consent}
          disabled={recording || busy}
          onChange={(e) => setConsent(e.target.checked)}
        />{" "}
        I consent to storing this speaker's encrypted voice template.
      </label>
      <button
        type="button"
        className="secondary"
        disabled={
          busy || disabled || (!recording && (!consent || !label.trim()))
        }
        onClick={() => void (recording ? finish() : start())}
      >
        {recording ? "Finish enrollment recording" : "Record enrollment sample"}
      </button>
      {recording && (
        <button type="button" onClick={stop}>
          Cancel enrollment
        </button>
      )}
      {speakers.map((s) => (
        <p key={s.speaker_id}>
          {s.label} · {s.role}{" "}
          <button
            type="button"
            disabled={busy || recording || disabled}
            onClick={() => {
              setBusy(true);
              void bridge
                .api("/developer/voice/remove", { speaker_id: s.speaker_id })
                .then(refresh)
                .catch((e) => setNotice(friendlyError(e)))
                .finally(() => setBusy(false));
            }}
          >
            Remove template
          </button>
        </p>
      ))}
      {notice && <p role="status">{notice}</p>}
    </details>
  );
}
