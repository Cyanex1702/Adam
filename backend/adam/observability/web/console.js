"use strict";
const node = id => document.getElementById(id);
let unlocked = false;
let authorizationEpoch = 0;
function lock(message) {
  authorizationEpoch++;
  unlocked = false;
  node("workspace").hidden = true;
  node("login").hidden = false;
  for (const id of ["health", "events", "detail", "evidence", "taskgraph", "replayed", "scenario", "hardware", "compute", "models", "benchmark"]) node(id).replaceChildren();
  for (const id of ["password", "query", "task", "model-json", "benchmark-id"]) node(id).value = "";
  node("reduced").checked = false;
  node("notice").textContent = message;
}
async function request(path, body) {
  const epoch = authorizationEpoch;
  const response = await fetch(path, {method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
    headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) lock("Developer authorization expired or was denied.");
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.error === "string" ? failure.error : "Request failed: " + response.status);
  }
  const value = await response.json();
  if (epoch !== authorizationEpoch) throw new Error("Authorization changed; response discarded.");
  return value;
}
const render = (id, value) => { node(id).textContent = JSON.stringify(value, null, 2); };
async function refresh() {
  render("health", await request("/developer/health"));
  render("compute", await request("/developer/compute"));
  render("models", await request("/developer/models"));
  const events = await request("/developer/traces");
  node("events").replaceChildren();
  for (const event of events.slice().reverse()) {
    const row = document.createElement("tr");
    for (const value of [event.trace_id, event.subsystem, event.event, event.status, event.duration_ms ?? "—"]) {
      const cell = document.createElement("td"); cell.textContent = String(value); row.append(cell);
    }
    const button = document.createElement("button"); button.textContent = event.trace_id.slice(0, 8);
    button.onclick = () => request("/developer/traces/" + encodeURIComponent(event.trace_id)).then(value => render("detail", value)).catch(showError);
    row.firstChild.replaceChildren(button); node("events").append(row);
  }
}
function showError(error) { node("notice").textContent = error.message; }
node("login").onsubmit = async event => {
  event.preventDefault(); const password = node("password").value;
  try {
    await request("/auth/login", {password}); await request("/auth/elevate", {password});
    node("login").hidden = true; node("workspace").hidden = false; unlocked = true;
    node("notice").textContent = "Developer mode unlocked for five minutes.";
    await refresh();
    const scenarios = await request("/developer/evals/scenarios");
    for (const scenario of scenarios) { const option = document.createElement("option"); option.value = scenario; option.textContent = scenario; node("scenario").append(option); }
  } catch (error) { showError(error); } finally { node("password").value = ""; }
};
node("refresh").onclick = () => refresh().catch(showError);
node("logout").onclick = async () => { try { await request("/auth/logout", {}); } finally { lock("Logged out."); } };
node("inspect").onsubmit = async event => { event.preventDefault(); try {
  const query = encodeURIComponent(node("query").value);
  render("evidence", {memory: await request("/developer/memory?query=" + query), knowledge: await request("/developer/knowledge?query=" + query)});
} catch (error) { showError(error); } };
node("graph").onsubmit = async event => { event.preventDefault(); try { render("taskgraph", await request("/developer/tasks/" + encodeURIComponent(node("task").value))); } catch (error) { showError(error); } };
node("replay").onclick = () => request("/developer/evals/replay/" + encodeURIComponent(node("scenario").value), {}).then(value => render("replayed", value)).catch(showError);
setInterval(() => { if (unlocked) request("/developer/traces").catch(showError); }, 15000);
node("hardware-refresh").onclick = () => request("/developer/hardware?benchmark=true").then(value => render("hardware", value)).catch(showError);
for (const action of ["load", "unload"]) node("model-" + action).onclick = () => request("/developer/compute/" + action, {}).then(refresh).catch(showError);
node("model-register").onsubmit = async event => { event.preventDefault(); try { await request("/developer/models", JSON.parse(node("model-json").value)); await refresh(); } catch (error) { showError(error); } };
node("model-benchmark").onsubmit = async event => { event.preventDefault(); node("notice").textContent = "Benchmark running in isolated stores; compute is reserved."; try { const result = await request("/developer/models/" + encodeURIComponent(node("model-id").value) + "/benchmark", {}); render("benchmark", result); node("benchmark-id").value = result.benchmark_id; node("notice").textContent = result.eligible ? "Benchmark passed; trial is available." : "Benchmark gates failed; default unchanged."; await refresh(); } catch (error) { showError(error); } };
node("model-promote").onsubmit = async event => { event.preventDefault(); try { await request("/developer/models/" + encodeURIComponent(node("model-id").value) + "/promote", {benchmark_id: node("benchmark-id").value, acknowledge_reduced: node("reduced").checked}); await refresh(); } catch (error) { showError(error); } };
for (const action of ["finalize", "rollback"]) node("model-" + action).onclick = () => request("/developer/models/" + action, {}).then(refresh).catch(showError);
