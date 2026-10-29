#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod job;
mod reply_clock;
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Read, Write},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager, State};
use tokio::sync::watch;

struct Backend {
    child: Child,
    port: u16,
    nonce: String,
    token: Option<String>,
    _job: job::Job,
}
struct AppState {
    backend: Mutex<Option<Backend>>,
    starting: AtomicBool,
    busy: AtomicBool,
    epoch: AtomicU64,
    cancel: watch::Sender<u64>,
    background: AtomicBool,
    tray_available: AtomicBool,
}
struct Busy<'a>(&'a AtomicBool);
impl Drop for Busy<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

fn allowed(method: &str, path: &str) -> bool {
    if path.len() > 4096 || path.contains(['\r', '\n', '#', '\\']) {
        return false;
    }
    let route = path.split('?').next().unwrap_or("");
    let parts: Vec<_> = route.split('/').collect();
    let session =
        parts.len() == 4 && parts[1] == "sessions" && uuid::Uuid::parse_str(parts[2]).is_ok();
    if path.contains('?')
        && !(method == "GET"
            && (route == "/memory"
                || route == "/personal/evidence"
                || route == "/developer/hardware"
                || (session && parts[3] == "history")))
    {
        return false;
    }
    if method == "GET"
        && [
            "/desktop/status",
            "/desktop/diagnostics",
            "/diagnostics",
            "/performance",
            "/models/library",
            "/voice/status",
            "/voice/speakers",
            "/health",
            "/auth/status",
            "/identity",
            "/models",
            "/sessions",
            "/memory",
            "/memory/candidates",
            "/developer/health",
            "/developer/traces",
            "/developer/compute",
            "/developer/models",
            "/developer/hardware",
            "/developer/mesh",
            "/internet",
            "/vision",
            "/vision/windows",
            "/computer",
            "/computer/windows",
            "/distribution",
            "/distribution/setup",
            "/personal",
            "/personal/evidence",
            "/training",
            "/training/recipe",
            "/portfolio",
            "/portfolio/benchmarks",
            "/operations",
            "/operations/inbox",
        ]
        .contains(&route)
    {
        return true;
    }
    if method == "POST"
        && [
            "/desktop/setup",
            "/performance",
            "/model/reload",
            "/model/device",
            "/models/scan",
            "/models/approve",
            "/models/automatic",
            "/models/select",
            "/voice/transcribe",
            "/developer/voice/enroll",
            "/developer/voice/remove",
            "/voice/turn",
            "/voice/speak",
            "/auth/login",
            "/auth/session",
            "/auth/switch",
            "/auth/elevate",
            "/auth/logout",
            "/developer/compute/load",
            "/developer/compute/unload",
            "/developer/mesh/start",
            "/developer/mesh/stop",
            "/developer/mesh/code",
            "/developer/mesh/approve",
            "/developer/mesh/revoke",
            "/developer/mesh/share",
            "/developer/mesh/handoff",
            "/mesh/session-state",
            "/internet/configure",
            "/internet/search",
            "/internet/fetch",
            "/internet/connect",
            "/internet/disconnect",
            "/internet/browser",
            "/internet/preview",
            "/internet/approve",
            "/internet/execute",
            "/internet/cancel",
            "/vision/configure",
            "/vision/analyze",
            "/vision/capture",
            "/computer/configure",
            "/computer/observe",
            "/computer/plan",
            "/computer/approve",
            "/computer/execute",
            "/distribution/stage",
            "/distribution/authorize",
            "/distribution/handoff",
            "/distribution/backup",
            "/distribution/restore",
            "/distribution/reindex",
            "/distribution/model",
            "/distribution/cancel",
            "/personal/graph",
            "/personal/timeline",
            "/personal/link",
            "/personal/goal",
            "/personal/remove",
            "/training/configure",
            "/training/example",
            "/training/remove",
            "/training/dataset",
            "/training/compare",
            "/portfolio/demo-tool",
            "/operations/schedule",
            "/operations/cancel",
            "/operations/preferences",
            "/operations/acknowledge",
        ]
        .contains(&route)
    {
        return true;
    }
    session
        && ((method == "GET" && parts[3] == "history")
            || (method == "POST" && parts[3] == "resume"))
}

fn stop(backend: &mut Backend) {
    if let Some(mut input) = backend.child.stdin.take() {
        let _ = input.write_all(b"stop\n");
    }
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        if matches!(backend.child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = backend.child.kill();
    let _ = backend.child.wait();
}

fn launch(app: &tauri::AppHandle) -> Result<Backend, String> {
    let root = app
        .path()
        .resource_dir()
        .map_err(|_| "DESKTOP.RESOURCES_MISSING")?;
    #[cfg(debug_assertions)]
    let root = if !root.join("backend/adam-service.exe").is_file() {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources")
    } else {
        root
    };
    let executable = root.join("backend/adam-service.exe");
    if !executable.is_file() {
        return Err("DESKTOP.SERVICE_MISSING".into());
    }
    let mut command = Command::new(executable);
    command
        .env("ADAM_DESKTOP_HOST", "1")
        .arg("--config")
        .arg(root.join("adam.compact.toml"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    #[cfg(debug_assertions)]
    {
        if let Ok(directory) = std::env::var("ADAM_DESKTOP_QA_DIR") {
            command.arg("--data-dir").arg(directory);
        }
        if std::env::var("ADAM_DESKTOP_PROBE").as_deref() == Ok("1") {
            command.arg("--probe");
        }
    }
    let mut child = command.spawn().map_err(|_| "DESKTOP.START_FAILED")?;
    let guard = match job::Job::attach(&child) {
        Ok(job) => job,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    let output = child.stdout.take().ok_or("DESKTOP.START_FAILED")?;
    let (tx, rx) = std::sync::mpsc::sync_channel(1);
    std::thread::spawn(move || {
        let mut line = String::new();
        let mut reader = BufReader::new(output).take(8192);
        let _ = reader.read_line(&mut line);
        let _ = tx.send(line);
    });
    let receipt = rx
        .recv_timeout(Duration::from_secs(150))
        .ok()
        .and_then(|line| serde_json::from_str::<Value>(&line).ok());
    if let Some(failed) = receipt.as_ref().filter(|value| value["event"] == "failed") {
        let code = error(failed, "DESKTOP.START_FAILED");
        let _ = child.kill();
        let _ = child.wait();
        return Err(code);
    }
    let valid = receipt
        .as_ref()
        .filter(|value| value["event"] == "ready")
        .and_then(|value| {
            Some((
                u16::try_from(value["port"].as_u64()?).ok()?,
                value["nonce"].as_str()?.to_string(),
            ))
        });
    match valid {
        Some((port, nonce)) if port > 1024 && nonce.len() >= 32 => Ok(Backend {
            child,
            port,
            nonce,
            token: None,
            _job: guard,
        }),
        _ => {
            let _ = child.kill();
            let _ = child.wait();
            Err("DESKTOP.START_TIMEOUT".into())
        }
    }
}

#[tauri::command]
async fn backend_start(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    restart: bool,
) -> Result<Value, String> {
    if state.starting.swap(true, Ordering::SeqCst) {
        return Err("DESKTOP.STARTING".into());
    }
    let _guard = Busy(&state.starting);
    let previous = {
        let mut lock = state.backend.lock().map_err(|_| "DESKTOP.STATE_FAILED")?;
        if !restart
            && lock
                .as_mut()
                .is_some_and(|backend| matches!(backend.child.try_wait(), Ok(None)))
        {
            return Ok(json!({"running":true}));
        }
        state.cancel.send_modify(|value| *value += 1);
        state.epoch.fetch_add(1, Ordering::SeqCst);
        lock.take()
    };
    let backend = tauri::async_runtime::spawn_blocking(move || {
        if let Some(mut previous) = previous {
            stop(&mut previous);
        }
        launch(&app)
    })
    .await
    .map_err(|_| "DESKTOP.START_FAILED")??;
    *state.backend.lock().map_err(|_| "DESKTOP.STATE_FAILED")? = Some(backend);
    Ok(json!({"running":true}))
}

fn connection(state: &AppState) -> Result<(u16, String, Option<String>), String> {
    let mut lock = state.backend.lock().map_err(|_| "DESKTOP.STATE_FAILED")?;
    let backend = lock.as_mut().ok_or("DESKTOP.OFFLINE")?;
    if !matches!(backend.child.try_wait(), Ok(None)) {
        backend.token = None;
        return Err("DESKTOP.BACKEND_STOPPED".into());
    }
    Ok((backend.port, backend.nonce.clone(), backend.token.clone()))
}

#[tauri::command]
async fn background_mode(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    enabled: bool,
) -> Result<Value, String> {
    if enabled {
        if !state.tray_available.load(Ordering::SeqCst) {
            return Err("DESKTOP.TRAY_UNAVAILABLE".into());
        }
        let (port, nonce, token) = connection(&state)?;
        let response = client()?
            .get(format!("http://127.0.0.1:{port}/auth/status"))
            .header("x-adam-desktop", nonce)
            .bearer_auth(token.ok_or("AUTH.REQUIRED")?)
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .map_err(|_| "DESKTOP.CONNECTION_LOST")?;
        let value: Value = response
            .json()
            .await
            .map_err(|_| "DESKTOP.REQUEST_FAILED")?;
        if value["mode"] != "owner" {
            return Err("POLICY.OWNER_REQUIRED".into());
        }
    }
    state.background.store(enabled, Ordering::SeqCst);
    if let Some(tray) = app.tray_by_id("adam-status") {
        let _ = tray.set_tooltip(Some(if enabled {
            "ADAM running · background enabled · open to see activity"
        } else {
            "ADAM running · close window to quit"
        }));
    }
    Ok(json!({"enabled":enabled}))
}

#[tauri::command]
fn background_status(state: State<'_, AppState>) -> Value {
    json!({"enabled":state.background.load(Ordering::SeqCst),
           "tray_available":state.tray_available.load(Ordering::SeqCst)})
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.state::<AppState>()
        .background
        .store(false, Ordering::SeqCst);
    app.exit(0);
}
fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "DESKTOP.TRANSPORT_FAILED".into())
}
fn error(value: &Value, fallback: &str) -> String {
    let code = value["error"].as_str().unwrap_or(fallback);
    if !code.is_empty()
        && code.len() <= 100
        && code
            .chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '.' || c == '_')
    {
        code.into()
    } else {
        fallback.into()
    }
}

#[tauri::command]
async fn api_request(
    state: State<'_, AppState>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    let voice = path.starts_with("/voice/") || path.starts_with("/developer/voice/");
    let input_limit = if path == "/voice/transcribe" || path == "/developer/voice/enroll" {
        2_570_000
    } else if path == "/vision/analyze" {
        4_210_000
    } else {
        65536
    };
    if !allowed(&method, &path)
        || body
            .as_ref()
            .is_some_and(|value| value.to_string().len() > input_limit)
    {
        return Err("DESKTOP.REQUEST_DENIED".into());
    }
    let (port, nonce, token) = connection(&state)?;
    let changes_auth = [
        "/auth/login",
        "/auth/session",
        "/auth/switch",
        "/auth/logout",
    ]
    .contains(&path.as_str());
    let epoch = if changes_auth {
        state.cancel.send_modify(|value| *value += 1);
        let epoch = state.epoch.fetch_add(1, Ordering::SeqCst) + 1;
        if let Some(backend) = state
            .backend
            .lock()
            .map_err(|_| "DESKTOP.STATE_FAILED")?
            .as_mut()
        {
            backend.token = None;
        }
        epoch
    } else {
        state.epoch.load(Ordering::SeqCst)
    };
    let mut request = client()?
        .request(
            method.parse().map_err(|_| "DESKTOP.REQUEST_DENIED")?,
            format!("http://127.0.0.1:{port}{path}"),
        )
        .header("x-adam-desktop", nonce)
        .timeout(Duration::from_secs(if voice {
            180
        } else if path.starts_with("/computer")
            || path.starts_with("/distribution")
            || path.starts_with("/models/")
            || path == "/model/reload"
            || path == "/model/device"
            || path == "/performance"
        {
            300
        } else if path.starts_with("/vision") {
            90
        } else {
            30
        }));
    if let Some(token) = token {
        request = request.bearer_auth(token);
    }
    if let Some(body) = body {
        request = request.json(&body);
    }
    let response = request.send().await.map_err(|error| {
        if error.is_timeout() {
            "DESKTOP.REQUEST_TIMEOUT"
        } else {
            "DESKTOP.CONNECTION_LOST"
        }
    })?;
    let status = response.status();
    let output_limit = if path == "/voice/speak" {
        3 * 1024 * 1024
    } else {
        2 * 1024 * 1024
    };
    if response
        .content_length()
        .is_some_and(|length| length > output_limit as u64)
    {
        return Err("DESKTOP.RESPONSE_LIMIT".into());
    }
    let mut bytes = Vec::new();
    let mut chunks = response.bytes_stream();
    while let Some(chunk) = chunks.next().await {
        bytes.extend_from_slice(&chunk.map_err(|_| "DESKTOP.CONNECTION_LOST")?);
        if bytes.len() > output_limit {
            return Err("DESKTOP.RESPONSE_LIMIT".into());
        }
    }
    let mut value: Value = serde_json::from_slice(&bytes).map_err(|_| "DESKTOP.PROTOCOL_ERROR")?;
    if state.epoch.load(Ordering::SeqCst) != epoch {
        return Err("AUTH.CHANGED".into());
    }
    if !status.is_success() {
        if status.as_u16() == 401 {
            if let Some(backend) = state
                .backend
                .lock()
                .map_err(|_| "DESKTOP.STATE_FAILED")?
                .as_mut()
            {
                backend.token = None;
            }
            state.cancel.send_modify(|value| *value += 1);
            state.epoch.fetch_add(1, Ordering::SeqCst);
        }
        return Err(error(&value, "DESKTOP.REQUEST_FAILED"));
    }
    let returned_token = value.get("token").and_then(Value::as_str).map(String::from);
    if let Some(object) = value.as_object_mut() {
        object.remove("token");
    }
    if changes_auth {
        if let Some(backend) = state
            .backend
            .lock()
            .map_err(|_| "DESKTOP.STATE_FAILED")?
            .as_mut()
        {
            backend.token = returned_token;
        }
    }
    Ok(value)
}

#[tauri::command]
async fn chat(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    request_id: String,
    body: Value,
) -> Result<Value, String> {
    if uuid::Uuid::parse_str(&request_id).is_err() || body.to_string().len() > 65536 {
        return Err("DESKTOP.REQUEST_DENIED".into());
    }
    if state.busy.swap(true, Ordering::SeqCst) {
        return Err("SESSION.BUSY".into());
    }
    let _guard = Busy(&state.busy);
    let mut cancel = state.cancel.subscribe();
    let (port, nonce, token) = connection(&state)?;
    let epoch = state.epoch.load(Ordering::SeqCst);
    let token = token.ok_or("AUTH.REQUIRED")?;
    let mut clock =
        reply_clock::ReplyClock::new(Instant::now(), body["careful"].as_bool().unwrap_or(false));
    let (progress, mut progress_rx) = watch::channel(0u64);
    let operation = async {
        let response = client()?
            .post(format!("http://127.0.0.1:{port}/desktop/chat"))
            .header("x-adam-desktop", nonce)
            .bearer_auth(token)
            .json(&body)
            .send()
            .await
            .map_err(|_| "DESKTOP.CONNECTION_LOST")?;
        if !response.status().is_success() {
            let mut chunks = response.bytes_stream();
            let mut bytes = Vec::new();
            while let Some(chunk) = chunks.next().await {
                bytes.extend_from_slice(&chunk.map_err(|_| "DESKTOP.CONNECTION_LOST")?);
                if bytes.len() > 8192 {
                    return Err("DESKTOP.RESPONSE_LIMIT".into());
                }
            }
            let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
            return Err(error(&value, "DESKTOP.CHAT_DENIED"));
        }
        let mut stream = response.bytes_stream();
        let mut buffer = Vec::new();
        let mut terminal = false;
        while let Some(chunk) = stream.next().await {
            buffer.extend_from_slice(&chunk.map_err(|_| "DESKTOP.CONNECTION_LOST")?);
            if buffer.len() > 1024 * 1024 {
                return Err("DESKTOP.RESPONSE_LIMIT".into());
            }
            while let Some(end) = buffer.iter().position(|byte| *byte == b'\n') {
                let line: Vec<_> = buffer.drain(..=end).collect();
                let event: Value =
                    serde_json::from_slice(&line).map_err(|_| "DESKTOP.PROTOCOL_ERROR")?;
                if state.epoch.load(Ordering::SeqCst) != epoch {
                    return Err("AUTH.CHANGED".into());
                }
                if ["agent.completed", "agent.error"]
                    .contains(&event["event_type"].as_str().unwrap_or(""))
                {
                    terminal = true;
                }
                if event["event_type"] == "agent.token"
                    && event["payload"]["text"]
                        .as_str()
                        .is_some_and(|text| !text.is_empty())
                {
                    progress.send_modify(|value| *value += 1);
                }
                app.emit("adam:event", json!({"request_id":request_id,"event":event}))
                    .map_err(|_| "DESKTOP.EVENT_FAILED")?;
            }
        }
        if !terminal || !buffer.is_empty() {
            return Err("DESKTOP.STREAM_INTERRUPTED".into());
        }
        Ok(json!({"finished":true}))
    };
    tokio::pin!(operation);
    loop {
        tokio::select! {
            result=&mut operation=>return result,
            _=cancel.changed()=>return Ok(json!({"cancelled":true})),
            _=progress_rx.changed()=>clock.text_received(Instant::now()),
            _=tokio::time::sleep(clock.remaining(Instant::now()))=>return Err("MODEL.TIMEOUT".into()),
        }
    }
}
#[tauri::command]
fn cancel_chat(state: State<'_, AppState>) {
    state.cancel.send_modify(|value| *value += 1);
}

#[tauri::command]
async fn apply_release(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    ticket: String,
    token: String,
) -> Result<(), String> {
    if uuid::Uuid::parse_str(&ticket).is_err() || token.len() > 100 {
        return Err("UPDATE.APPROVAL_REQUIRED".into());
    }
    let paths = api_request(
        state.clone(),
        "POST".into(),
        "/distribution/handoff".into(),
        Some(json!({"ticket":ticket,"token":token})),
    )
    .await?;
    let root = app
        .path()
        .resource_dir()
        .map_err(|_| "DESKTOP.PATH_FAILED")?;
    let mut command = Command::new(root.join("backend").join("adam-service.exe"));
    command
        .arg("--release-apply")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut helper = command.spawn().map_err(|_| "UPDATE.HELPER_FAILED")?;
    let payload = json!({"home":paths["home"],"data":paths["data"],"ticket":ticket,"token":token,"parent":std::process::id()});
    helper
        .stdin
        .take()
        .ok_or("UPDATE.HELPER_FAILED")?
        .write_all(payload.to_string().as_bytes())
        .map_err(|_| "UPDATE.HELPER_FAILED")?;
    {
        let mut lock = state.backend.lock().map_err(|_| "DESKTOP.STATE_FAILED")?;
        if let Some(mut backend) = lock.take() {
            stop(&mut backend);
        }
    }
    app.exit(0);
    Ok(())
}

fn main() {
    // Normal shortcuts and direct EXE launches follow the verified generation.
    // Explicit test/custom data directories retain their existing native ownership path.
    if std::env::var_os("ADAM_MANAGED_LAUNCH").is_none()
        && std::env::var_os("ADAM_DATA_DIR").is_none()
    {
        if let Ok(executable) = std::env::current_exe() {
            if let Some(root) = executable.parent() {
                let mut command = Command::new(root.join("backend").join("adam-service.exe"));
                command
                    .arg("--release-launch")
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    command.creation_flags(0x08000000);
                }
                if command.status().is_ok_and(|status| status.success()) {
                    return;
                }
            }
        }
    }
    let (cancel, _) = watch::channel(0);
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(AppState {
            backend: Mutex::new(None),
            starting: AtomicBool::new(false),
            busy: AtomicBool::new(false),
            epoch: AtomicU64::new(0),
            cancel,
            background: AtomicBool::new(false),
            tray_available: AtomicBool::new(false),
        })
        .setup(|app| {
            use tauri::{
                menu::{Menu, MenuItem},
                tray::TrayIconBuilder,
            };
            // A failed tray must never strand a hidden application.
            let created = (|| -> tauri::Result<()> {
                let show = MenuItem::with_id(
                    app,
                    "show",
                    "Open ADAM / view activity",
                    true,
                    None::<&str>,
                )?;
                let quit = MenuItem::with_id(
                    app,
                    "quit",
                    "Quit ADAM and stop owned model",
                    true,
                    None::<&str>,
                )?;
                let menu = Menu::with_items(app, &[&show, &quit])?;
                let mut builder = TrayIconBuilder::with_id("adam-status")
                    .tooltip("ADAM running · close window to quit")
                    .menu(&menu)
                    .on_menu_event(|app, event| match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.unminimize();
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "quit" => {
                            app.state::<AppState>()
                                .background
                                .store(false, Ordering::SeqCst);
                            app.exit(0);
                        }
                        _ => {}
                    });
                if let Some(icon) = app.default_window_icon() {
                    builder = builder.icon(icon.clone());
                }
                builder.build(app)?;
                Ok(())
            })();
            app.state::<AppState>()
                .tray_available
                .store(created.is_ok(), Ordering::SeqCst);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<AppState>();
                if state.background.load(Ordering::SeqCst)
                    && state.tray_available.load(Ordering::SeqCst)
                {
                    // Reset capture before hiding; visibilitychange independently stops it too.
                    let _ = window.emit("adam:hidden", ());
                    if window.hide().is_ok() {
                        api.prevent_close();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            apply_release,
            backend_start,
            api_request,
            chat,
            cancel_chat,
            background_mode,
            background_status,
            quit_app
        ])
        .build(tauri::generate_context!())
        .expect("ADAM desktop initialization failed");
    app.run(|app, event| {
        if let tauri::RunEvent::Exit = event {
            if let Ok(mut lock) = app.state::<AppState>().backend.lock() {
                if let Some(mut backend) = lock.take() {
                    stop(&mut backend);
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_routes_and_uuid_sessions_only() {
        assert!(allowed("GET", "/memory?query=editor"));
        assert!(allowed(
            "GET",
            "/sessions/7e9bb136-ec20-4c78-8c92-d33c62e27ef1/history"
        ));
        for path in [
            "https://example.com",
            "//example.com",
            "/vault/handles",
            "/sessions/../history",
            "/developer/models/current/promote",
            "/memory\r\nx:evil",
        ] {
            assert!(!allowed("GET", path));
        }
        assert!(!allowed("DELETE", "/memory"));
        assert!(!allowed("POST", "/sessions/not-a-uuid/resume"));
        assert!(!allowed("POST", "/auth/login?bypass=true"));
        assert!(allowed("GET", "/voice/speakers"));
        assert!(allowed("POST", "/developer/voice/enroll"));
        assert!(allowed("POST", "/developer/voice/remove"));
        assert!(!allowed("GET", "/developer/voice/enroll"));
        assert!(!allowed("POST", "/developer/voice/arbitrary"));
        assert!(allowed("GET", "/developer/mesh"));
        assert!(allowed("POST", "/model/device"));
        assert!(!allowed("GET", "/model/device"));
        assert!(!allowed("POST", "/model/arbitrary"));
        assert!(allowed("POST", "/developer/mesh/revoke"));
        assert!(allowed("POST", "/mesh/session-state"));
        assert!(!allowed("POST", "/developer/mesh/arbitrary"));
        assert!(!allowed("POST", "/rpc"));
        assert!(!allowed("POST", "/pair"));
        assert!(allowed("GET", "/internet"));
        assert!(allowed("POST", "/internet/execute"));
        assert!(!allowed("POST", "/internet/arbitrary"));
        assert!(!allowed("GET", "/internet?token=x"));
        assert!(allowed("GET", "/computer"));
        assert!(allowed("POST", "/computer/execute"));
        assert!(!allowed("POST", "/computer/arbitrary"));
        assert!(allowed("POST", "/distribution/authorize"));
        assert!(!allowed("POST", "/distribution/arbitrary"));
        assert!(allowed("GET", "/personal"));
        assert!(allowed("POST", "/personal/goal"));
        assert!(allowed("GET", "/personal/evidence?id=sample"));
        assert!(!allowed("POST", "/personal/arbitrary"));
        assert!(allowed("POST", "/training/compare"));
        assert!(!allowed("POST", "/training/activate"));
        assert!(allowed("GET", "/portfolio/benchmarks"));
        assert!(allowed("POST", "/portfolio/demo-tool"));
        assert!(!allowed("GET", "/portfolio?token=x"));
        assert!(allowed("GET", "/vision"));
        assert!(allowed("POST", "/vision/capture"));
        assert!(!allowed("POST", "/vision/arbitrary"));
        assert!(!allowed("GET", "/vision?token=x"));
        assert!(allowed("GET", "/operations/inbox"));
        assert!(allowed("POST", "/operations/schedule"));
        assert!(!allowed("POST", "/operations/arbitrary"));
        assert!(!allowed("GET", "/operations/inbox?device=phone"));
    }
    #[test]
    fn errors_never_echo_backend_text() {
        assert_eq!(
            error(&json!({"error":""}), "DESKTOP.REQUEST_FAILED"),
            "DESKTOP.REQUEST_FAILED"
        );
        assert_eq!(
            error(
                &json!({"error":"private path or password"}),
                "DESKTOP.REQUEST_FAILED"
            ),
            "DESKTOP.REQUEST_FAILED"
        );
        assert_eq!(
            error(&json!({"error":"AUTH.REQUIRED"}), "DESKTOP.REQUEST_FAILED"),
            "AUTH.REQUIRED"
        );
    }
    #[test]
    #[cfg(windows)]
    fn owned_job_terminates_only_its_child() {
        use std::os::windows::process::CommandExt;
        let mut child = Command::new("powershell.exe")
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Start-Sleep -Seconds 120",
            ])
            .creation_flags(0x08000000)
            .spawn()
            .unwrap();
        let guard = job::Job::attach(&child).unwrap();
        assert!(child.try_wait().unwrap().is_none());
        drop(guard);
        let deadline = Instant::now() + Duration::from_secs(10);
        while child.try_wait().unwrap().is_none() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(50));
        }
        let exited = child.try_wait().unwrap().is_some();
        if !exited {
            let _ = child.kill();
            let _ = child.wait();
        }
        assert!(exited);
    }
}
