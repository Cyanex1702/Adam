import { useEffect, useRef, useState } from "react";
import * as bridge from "./bridge";

export function InternetPanel({ issue }: { issue: (error: unknown) => void }) {
  const [status, setStatus] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [page, setPage] = useState<any>(null);
  const [password, setPassword] = useState("");
  const [query, setQuery] = useState("");
  const [searchProvider, setSearchProvider] = useState("hackernews");
  const [searchEndpoint, setSearchEndpoint] = useState("");
  const [url, setUrl] = useState("https://example.com/");
  const [endpoint, setEndpoint] = useState("");
  const [names, setNames] = useState("");
  const [argumentsText, setArgumentsText] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const generation = useRef(0), alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    async function load() {
      if (document.hidden) {
        generation.current++;
        setStatus(null); setPage(null); setEvidence(null); setPassword("");
        setQuery(""); setArgumentsText("{}");
        setUrl("https://example.com/"); setEndpoint(""); setNames(""); setNote("");
        return;
      }
      const expected = generation.current;
      try {
        const next = await bridge.api("/internet");
        if (alive.current && expected === generation.current) setStatus(next);
      } catch (error) {
        if (alive.current && expected === generation.current) issue(error);
      }
    }
    void load();
    document.addEventListener("visibilitychange", load);
    return () => {
      alive.current = false; generation.current++;
      document.removeEventListener("visibilitychange", load);
    };
  }, []);
  async function run(path: string, body: unknown, target?: "page" | "evidence", elevated = false) {
    if (busy || document.hidden) return;
    const expected = generation.current, secret = password;
    setBusy(true); setNote("");
    if (elevated) setPassword("");
    try {
      if (elevated) await bridge.api("/auth/elevate", { password: secret });
      if (!alive.current || expected !== generation.current || document.hidden) return;
      const result = await bridge.api(path, body);
      const next = await bridge.api("/internet");
      if (alive.current && expected === generation.current) {
        setStatus(next);
        if (target === "page") setPage(result.closed ? null : result);
        if (target === "evidence") setEvidence(result);
        if (!next.enabled) { setPage(null); setEvidence(null); }
        setNote("Done.");
      }
    } catch (error) {
      if (alive.current && expected === generation.current) issue(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function execute(action: any) {
    if (busy || document.hidden) return;
    const expected = generation.current, secret = password;
    setPassword(""); setBusy(true); setNote("");
    try {
      await bridge.api("/auth/elevate", { password: secret });
      if (!alive.current || expected !== generation.current || document.hidden) return;
      await bridge.api("/internet/approve", { identifier: action.id, digest: action.digest });
      if (!alive.current || expected !== generation.current || document.hidden) return;
      setStatus((old: any) => ({ ...old, actions: old.actions.map((item: any) => item.id === action.id ? { ...item, state: "RUNNING" } : item) }));
      const result = await bridge.api("/internet/execute", { identifier: action.id });
      const next = await bridge.api("/internet");
      if (alive.current && expected === generation.current) {
        setStatus(next);
        setNote(result.state === "REPORTED" ? "Response received. Check the external result." :
          "Outcome uncertain. Check the external service before attempting another action.");
      }
    } catch (error) {
      if (alive.current && expected === generation.current) issue(error);
    } finally { if (alive.current) setBusy(false); }
  }
  return <section className="page operations">
    <span className="section-number">INTERNET AND INTEGRATIONS</span>
    <h2>External evidence and actions</h2>
    <p>Enable access for this login. Search terms, requested URLs and approved arguments go to
      the selected public service. Local chat and memory stay separate. Access starts off after
      restart or a new login.</p>
    <label>Reauthenticate to enable access, connect a provider or execute an action
      <input type="password" autoComplete="off" value={password}
        onChange={event => setPassword(event.target.value)} />
    </label>
    <button disabled={busy || (!status?.enabled && !password)}
      onClick={() => void run("/internet/configure", { enabled: !status?.enabled }, undefined, !status?.enabled)}>
      {status?.enabled ? "Disable access and clear this workspace" : "Enable Internet for this login"}
    </button>
    <p role="status">{note}</p>
    {status?.enabled && <>
      <h3>Web evidence</h3>
      <p>Choose a search source or fetch a public HTTPS page by URL. Excerpts are attributed
        evidence; ADAM has not verified their claims. Search services can reject or rate-limit requests.</p>
      <form onSubmit={event => { event.preventDefault(); void run("/internet/search", {
        query, provider: searchProvider, endpoint: searchProvider === "searxng" ? searchEndpoint : "",
      }, "evidence"); }}>
        <label>Search source<select value={searchProvider} onChange={event => setSearchProvider(event.target.value)}>
          <option value="hackernews">Hacker News — technology/community stories</option>
          <option value="wikipedia">Wikipedia — encyclopedia articles</option>
          <option value="searxng">My SearXNG instance — general web</option>
        </select></label>
        {searchProvider === "searxng" && <label>SearXNG HTTPS search endpoint (JSON must be enabled)
          <input required value={searchEndpoint} onChange={event => setSearchEndpoint(event.target.value)} placeholder="https://your-instance.example/search" /></label>}
        <label>Search terms<input required maxLength={256} value={query} onChange={event => setQuery(event.target.value)} /></label>
        <button disabled={busy}>Search</button>
      </form>
      <form onSubmit={event => { event.preventDefault(); void run("/internet/fetch", { url }, "evidence"); }}>
        <label>Public HTTPS URL<input required value={url} onChange={event => setUrl(event.target.value)} /></label>
        <button disabled={busy}>Fetch evidence</button>
        <button type="button" disabled={busy} onClick={() => void run("/internet/browser", { operation: "navigate", url }, "page")}>Open text browser</button>
      </form>
      {evidence && <article className="memory-card">
        <small>{evidence.provider || evidence.source_kind} · {evidence.freshness}</small>
        {(evidence.sources || [evidence]).map((source: any, index: number) => <div key={index}>
          <h4>{source.title}</h4><p>{source.url}</p>
          <small>Fetched {new Date(source.fetched_at * 1000).toLocaleString()} · {source.published_at || source.updated_at || source.last_modified || "Publication date unavailable"}</small>
          <p style={{ whiteSpace: "pre-wrap" }}>{source.text}</p>
        </div>)}
        <button disabled={busy} onClick={() => setEvidence(null)}>Clear evidence</button>
      </article>}
      <h3>Text browser</h3>
      <p>Reads HTML without scripts, cookies or a signed-in browser profile. Simple text inputs
        can be filled locally. Passwords, uploads and file downloads are unavailable. Dynamic
        sites may need your regular browser.</p>
      {page && <article className="memory-card">
        <h4>{page.title}</h4><p>{page.url}</p>
        <p style={{ whiteSpace: "pre-wrap" }}>{page.text}</p>
        <details><summary>Page links</summary>{page.links?.map((link: any, index: number) =>
          <button key={index} disabled={busy} onClick={() => void run("/internet/browser", { operation: "click", index }, "page")}>{link.url}</button>)}</details>
        {page.forms?.map((form: any, index: number) => <fieldset key={index} disabled={busy}>
          <legend>Form {index + 1} · {form.method} {form.action || page.url}</legend>
          {Object.entries(form.fields).map(([name, field]: [string, any]) => <form key={name} onSubmit={event => {
            event.preventDefault(); const draft = new FormData(event.currentTarget);
            void run("/internet/browser", { operation: "type", index, field: name,
              text: String(draft.get("draft") || "") }, "page");
          }}><label>{name}<input name="draft" disabled={field.type === "hidden"} defaultValue={field.value} /></label>
            {field.type !== "hidden" && <button>Fill locally</button>}
          </form>)}
          <button disabled={busy || form.unsupported} onClick={() => void run("/internet/preview", { kind: "form", form: index })}>Preview submission</button>
        </fieldset>)}
        <button disabled={busy} onClick={() => void run("/internet/browser", { operation: "close" }, "page")}>Close text browser</button>
      </article>}
      <h3>External tool providers</h3>
      <p>Use an HTTPS MCP server you trust. Declare exact tool names before connecting.
        Every call requires review; server instructions cannot enable ADAM tools or read local
        files. The remote server controls its own implementation.</p>
      <form onSubmit={event => { event.preventDefault(); void run("/internet/connect", {
        url: endpoint, tools: names.split(",").map(value => value.trim()).filter(Boolean),
      }, undefined, true); }}>
        <label>MCP HTTPS endpoint<input required value={endpoint} onChange={event => setEndpoint(event.target.value)} /></label>
        <label>Allowed tool names (comma separated)<input required value={names} onChange={event => setNames(event.target.value)} /></label>
        <button disabled={busy || !password}>Connect and discover</button>
      </form>
      <label>Arguments for the next provider call (JSON object)<textarea value={argumentsText} onChange={event => setArgumentsText(event.target.value)} /></label>
      {status.providers.map((provider: any) => <article className="memory-card" key={provider.id}>
        <p>{provider.url}</p>
        {provider.tools.map((tool: any) => <div key={tool.name}>
          <h4>{tool.name}</h4><p>{tool.description}</p>
          <details><summary>Declared input schema</summary><pre>{JSON.stringify(tool.inputSchema, null, 2)}</pre></details>
          <button disabled={busy} onClick={() => {
            try { void run("/internet/preview", { kind: "provider", provider: provider.id,
              tool: tool.name, arguments: JSON.parse(argumentsText) }); }
            catch { issue("INPUT.INVALID"); }
          }}>Preview call</button>
        </div>)}
        <button disabled={busy} onClick={() => void run("/internet/disconnect", { identifier: provider.id })}>Disconnect</button>
      </article>)}
      <h3>Action review</h3>
      <p>Review the exact destination and payload. Execution may change external data. A
        response confirms receipt, not the external effect. Cancellation cannot recall a
        request already sent.</p>
      {status.actions.map((action: any) => <article className="memory-card" key={action.id}>
        <small>{action.state}</small><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(action.details, null, 2)}</pre>
        {action.state === "PREVIEW" && <button className="primary" disabled={busy || !password} onClick={() => void execute(action)}>Approve and execute this action</button>}
        {["PREVIEW", "APPROVED", "RUNNING"].includes(action.state) && <button disabled={busy && action.state !== "RUNNING"}
          onClick={() => { const expected = generation.current;
            void bridge.api("/internet/cancel", { identifier: action.id }).then(() => bridge.api("/internet")).then(next => {
              if (alive.current && expected === generation.current && !document.hidden) setStatus(next);
            }).catch(error => { if (alive.current && expected === generation.current) issue(error); });
          }}>Cancel action</button>}
        {action.result && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(action.result, null, 2)}</pre>}
      </article>)}
    </>}
  </section>;
}
