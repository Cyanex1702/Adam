import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";
import { base64Image, validImage } from "./vision";

export function VisionPanel({ issue }: { issue: (error: unknown) => void }) {
  const [status, setStatus] = useState<any>(null), [result, setResult] = useState<any>(null);
  const [password, setPassword] = useState(""), [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState("Read the visible text and identify any error message.");
  const [apps, setApps] = useState("notepad.exe"), [exclusions, setExclusions] = useState("");
  const [endpoint, setEndpoint] = useState(""), [modelId, setModelId] = useState("");
  const [route, setRoute] = useState("ocr"), [note, setNote] = useState("");
  const [windows, setWindows] = useState<any[]>([]);
  const alive = useRef(true), generation = useRef(0);
  useEffect(() => {
    alive.current = true;
    async function visibility() {
      const expected = ++generation.current;
      setResult(null); setPassword(""); setNote(""); setWindows([]);
      if (document.hidden) {
        setQuestion(""); setEndpoint(""); setModelId(""); setStatus(null);
        setExclusions(""); setApps("notepad.exe"); setRoute("ocr");
        void bridge.api("/vision/configure", { enabled: false }).catch(() => {});
        return;
      }
      try {
        const next = await bridge.api("/vision");
        if (alive.current && expected === generation.current) setStatus(next);
      } catch (error) { if (alive.current && expected === generation.current) issue(error); }
    }
    void visibility();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      alive.current = false; generation.current++;
      document.removeEventListener("visibilitychange", visibility);
      void bridge.api("/vision/configure", { enabled: false }).catch(() => {});
    };
  }, []);
  function current(expected: number) {
    return alive.current && expected === generation.current && !document.hidden;
  }
  async function enable(screen: boolean, expected: number) {
    const secret = password;
    setPassword("");
    await bridge.api("/auth/elevate", { password: secret });
    if (!current(expected)) throw "VISION.CANCELLED";
    return bridge.api("/vision/configure", {
      enabled: true, screen,
      allowed_apps: apps.split(",").map(value => value.trim()).filter(Boolean),
      excluded_titles: exclusions.split(",").map(value => value.trim()).filter(Boolean),
      model_endpoint: endpoint, model_id: modelId,
    });
  }
  async function stop() {
    generation.current++; setResult(null); setPassword(""); setNote(""); setWindows([]);
    try {
      const next = await bridge.api("/vision/configure", { enabled: false });
      if (alive.current) setStatus(next);
    } catch (error) { if (alive.current) issue(error); }
  }
  async function run(kind: "enable" | "arm" | "capture" | "image", file?: File, windowId = "") {
    if (busy || document.hidden) return;
    const expected = generation.current;
    setBusy(true); setResult(null); setNote("");
    try {
      let next: any;
      if (kind === "enable" || kind === "arm") {
        next = await enable(kind === "arm", expected);
        if (!current(expected)) { await bridge.api("/vision/configure", { enabled: false }); return; }
        setStatus(next);
      }
      if (kind === "arm") {
        next = await bridge.api("/vision/windows");
        if (current(expected)) {
          setWindows(next.windows);
          setNote(next.windows.length ? "Choose a listed window within 60 seconds. Capture reads it once." : "No eligible windows found. Open an allowed app and arm again.");
        }
        return;
      }
      if (kind === "capture") {
        setWindows([]);
        setNote("Capture notice is visible. This one-window capture begins after 3 seconds.");
        next = await bridge.api("/vision/capture", { question, route, window_id: windowId });
      } else if (kind === "image" && file) {
        if (!validImage(file)) throw "VISION.INVALID_IMAGE";
        const data = new Uint8Array(await file.arrayBuffer());
        if (!current(expected)) return;
        next = await bridge.api("/vision/analyze", { image_base64: base64Image(data), question, route });
      }
      if (!current(expected)) return;
      if (kind !== "enable") setResult(next);
      setNote(kind === "enable" ? "Vision enabled for this login. Screen capture remains off." : "Perception complete. No action was authorized.");
      next = await bridge.api("/vision");
      if (current(expected)) setStatus(next);
    } catch (error) { if (current(expected)) { setNote(""); issue(error); } }
    finally { if (alive.current) setBusy(false); }
  }
  return <section className="panel internet-panel">
    <h2>Vision</h2>
    <p>Read images locally. Windows OCR extracts text; a separately configured visual model can interpret scenes.
      Results can be wrong and never authorize clicks, typing, or tools.</p>
    <p role="status">Vision {status?.enabled ? "enabled" : "off"} · OCR {status?.ocr || "checking"} ·
      Visual model {status?.visual_model || "unavailable"} · Camera unavailable</p>
    <label>Owner passphrase (required to enable or capture)
      <input type="password" autoComplete="off" value={password} disabled={busy}
        onChange={event => setPassword(event.target.value)} /></label>
    <button disabled={busy || !password} onClick={() => void run("enable")}>Enable image reading</button>
    <button onClick={() => void stop()}>Disable and clear / cancel</button>
    <label>Question <input value={question} maxLength={1000} disabled={busy}
      onChange={event => setQuestion(event.target.value)} /></label>
    <label>Provider <select value={route} disabled={busy} onChange={event => setRoute(event.target.value)}>
      <option value="ocr">Windows OCR — text only</option>
      <option value="model">OCR + local visual model</option></select></label>
    <label>Choose one image (PNG, JPEG or WebP, up to 3 MiB)
      <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy || !status?.enabled}
        onChange={event => { const file = event.target.files?.[0]; event.target.value = "";
          if (file) void run("image", file); }} /></label>
    <h3>One window capture</h3>
    <p>Arm capture, then choose a listed window. A visible desktop notice appears for 3 seconds before it is read, once. Browsers, credential apps and sensitive window titles are blocked.
      Capture stops after this attempt. Unsupported or protected windows may return no image.</p>
    <label>Allowed app filenames, separated by commas
      <input value={apps} disabled={busy} maxLength={1000} onChange={event => setApps(event.target.value)} /></label>
    <label>Additional private title words, separated by commas
      <input value={exclusions} disabled={busy} maxLength={1000} onChange={event => setExclusions(event.target.value)} /></label>
    <button disabled={busy || !password || status?.screen_capture !== "AVAILABLE"}
      onClick={() => void run("arm")}>Arm and choose a window</button>
    {windows.map(window => <button key={window.id} disabled={busy}
      onClick={() => void run("capture", undefined, window.id)}>Capture {window.app}: {window.title || "Untitled"}</button>)}
    <details><summary>Optional local visual model</summary>
      <p>Requires your own multimodal server and image projector. The current text model cannot see images.
        Images stay on this PC; only a numeric 127.0.0.1 HTTP endpoint is accepted. ADAM does not start or download a model.</p>
      <label>Local server, for example http://127.0.0.1:8081
        <input value={endpoint} disabled={busy} onChange={event => setEndpoint(event.target.value)} /></label>
      <label>Model ID <input value={modelId} disabled={busy} onChange={event => setModelId(event.target.value)} /></label>
    </details>
    {note && <p role="status">{note}</p>}
    {result && <article>
      <h3>Unverified perception</h3>
      <img style={{ maxWidth: "100%", maxHeight: 500 }} alt="The image ADAM processed"
        src={"data:image/jpeg;base64," + result.image.preview_base64} />
      <p>{result.source.source} · {result.source.app || "Selected image"} · {result.image.width} × {result.image.height}</p>
      <p>{result.uncertainty}</p>
      <h4>Extracted text</h4><pre style={{ whiteSpace: "pre-wrap" }}>{result.text || "No text recognized."}</pre>
      <h4>Interpretation</h4><p>{result.interpretation}</p>
      {result.error_candidates?.length > 0 && <><h4>Possible error text</h4>
        <pre style={{ whiteSpace: "pre-wrap" }}>{result.error_candidates.join("\n")}</pre></>}
      <p>{result.guidance} This result is held in memory and is cleared when you leave this view.</p>
    </article>}
  </section>;
}
