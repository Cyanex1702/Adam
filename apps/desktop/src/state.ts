export type AvatarState =
  | "LISTENING"
  | "SPEAKING"
  | "IDLE"
  | "UNDERSTANDING"
  | "THINKING"
  | "SEARCHING"
  | "USING_TOOL"
  | "WAITING_FOR_PERMISSION"
  | "UNCERTAIN"
  | "ERROR"
  | "OFFLINE";
export type AgentEvent = {
  event_id?: string;
  event_type: string;
  session_id?: string;
  payload: Record<string, any>;
};
export type VisualEvent =
  | { kind: "connection"; online: boolean }
  | { kind: "request" }
  | { kind: "cancel" }
  | { kind: "backend"; event: AgentEvent };
export function visualState(
  previous: AvatarState,
  event: VisualEvent,
): AvatarState {
  if (event.kind === "connection")
    return event.online
      ? previous === "OFFLINE"
        ? "IDLE"
        : previous
      : "OFFLINE";
  if (event.kind === "request") return "UNDERSTANDING";
  if (event.kind === "cancel") return "IDLE";
  const value = event.event;
  if (value.event_type === "agent.error") return "ERROR";
  if (value.event_type === "agent.started")
    return value.payload.state === "RETRIEVING"
      ? "SEARCHING"
      : value.payload.state === "MEMORY"
        ? "UNDERSTANDING"
        : "THINKING";
  if (value.event_type === "agent.completed")
    return value.payload.epistemic_status === "UNCERTAIN"
      ? "UNCERTAIN"
      : "IDLE";
  if (value.event_type === "tool.started") return "USING_TOOL";
  if (value.event_type === "approval.required") return "WAITING_FOR_PERMISSION";
  if (value.event_type === "tool.completed") return "IDLE";
  return previous; // Unknown and future voice events never fabricate active capabilities.
}
export const stateCopy: Record<AvatarState, [string, string]> = {
  LISTENING: ["Listening", "The microphone is active for local transcription."],
  SPEAKING: ["Speaking", "Local speech audio is playing."],
  IDLE: ["Ready", "No operation in progress."],
  UNDERSTANDING: ["Preparing", "The local service is processing your request."],
  THINKING: ["Thinking", "The local model is generating a response."],
  SEARCHING: ["Searching", "Retrieval is processing local sources."],
  USING_TOOL: ["Using a tool", "An approved operation is in progress."],
  WAITING_FOR_PERMISSION: [
    "Waiting for permission",
    "An operation needs your approval.",
  ],
  UNCERTAIN: ["Answer ready", "Model-generated answers are unverified."],
  ERROR: ["Needs attention", "The last operation did not complete."],
  OFFLINE: [
    "Model offline",
    "Saved conversations and notes remain available after login.",
  ],
};
export function friendlyError(error: unknown): string {
  const code =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : "";
  const known: Record<string, string> = {
    "INTERNET.DISABLED": "Enable Internet access for this login first.",
    "COMPUTER.CANCELLED": "Computer actions were cancelled. Check the window; already dispatched effects may remain.",
    "COMPUTER.UI_CHANGED": "The window changed. Remaining steps stopped. Observe again before reviewing a new plan.",
    "COMPUTER.VERIFICATION_FAILED": "The expected result was not observed. Do not retry until you inspect the window.",
    "COMPUTER.PRIVATE_CONTROL_DENIED": "A sensitive, unsupported or ambiguous target was denied.",
    "COMPUTER.APPROVAL_REQUIRED": "Approve this exact plan with fresh owner reauthentication first.",
    "COMPUTER.OBSERVATION_EXPIRED": "Observe the window again; its earlier observation expired or was consumed.",
    "UPDATE.CHECKSUM_FAILED": "The selected package does not match the trusted SHA-256. Nothing was activated.",
    "UPDATE.CHANNEL_MISMATCH": "This package belongs to a different release channel.",
    "UPDATE.PACKAGE_INVALID": "The release package is invalid or incomplete. The current release is unchanged.",
    "UPDATE.HEALTH_FAILED": "Candidate validation failed. The prior version and profile remain active.",
    "UPDATE.STALE_APPROVAL": "The active release changed after review. Review and approve the current generation again.",
    "UPDATE.APPROVAL_REQUIRED": "Activation approval expired or was revoked. Review and approve again.",
    "SETUP.CHECKSUM_FAILED": "The download failed checksum verification and was not installed. Retry the pinned download.",
    "SETUP.DOWNLOAD_OR_IO_FAILED": "Setup could not finish the verified download or installation. Check disk space and connectivity, then retry.",
    "SETUP.HARDWARE_REDUCED_MODE": "This PC needs a smaller separately configured model. The 4B preset was not downloaded.",
    "SETUP.CANCELLED": "Model setup was cancelled. No model was started.",
    "VISION.DISABLED": "Enable image reading for this login first.",
    "VISION.INVALID_IMAGE": "Choose a valid static PNG, JPEG or WebP image, up to 3 MiB.",
    "VISION.IMAGE_LIMIT": "This image is too large. Use up to 3 MiB and 8 million pixels.",
    "VISION.PRIVATE_WINDOW_DENIED": "This window is private, protected or outside your allowed apps.",
    "VISION.SCREEN_NOT_ARMED": "Arm a fresh one-window capture first.",
    "VISION.CAPTURE_UNAVAILABLE": "This window cannot be captured. You can select a saved image instead.",
    "VISION.OCR_UNAVAILABLE": "Windows OCR is unavailable. Install a supported Windows OCR language pack.",
    "VISION.MODEL_UNAVAILABLE": "No working local visual model is configured. Try Windows OCR for text.",
    "VISION.MODEL_VISION_REQUIRED": "This local server does not advertise image support. Use a multimodal model and projector, or Windows OCR.",
    "VISION.LOCAL_ENDPOINT_REQUIRED": "Use a local HTTP server at 127.0.0.1 with an explicit port.",
    "VISION.WINDOW_CHANGED": "The selected window changed or its selection expired. Arm and choose it again.",
    "VISION.INDICATOR_UNAVAILABLE": "The visible capture notice could not start. Capture was denied.",
    "VISION.CAPTURE_TIMEOUT": "The capture worker did not start in time. Arm again when the PC is less busy.",
    "VISION.CAPTURE_RENDER_TIMEOUT": "The window did not render in time. Select a saved image instead.",
    "VISION.OCR_FAILED": "Text recognition could not finish. Try a clearer, smaller image.",
    "VISION.BUSY": "Image processing is already running. Cancel it or wait for the result.",
    "VISION.SECRET_DENIED": "Recognizable credential content was detected; the whole result was withheld.",
    "VISION.CANCELLED": "Perception was cancelled and the result was discarded.",
    "VISION.RESOURCE_PRESSURE": "Available memory is too low for image processing. Close unused apps.",
    "INTERNET.URL_DENIED": "Use a public HTTPS URL on port 443, without credentials or a fragment.",
    "INTERNET.ADDRESS_DENIED": "This destination resolves to a private, local or reserved address.",
    "INTERNET.NETWORK_UNAVAILABLE": "The external connection failed. Local features remain available.",
    "INTERNET.SEARCH_UNAVAILABLE": "This search source rejected the request or returned an unsupported response. Try another source.",
    "INTERNET.PROVIDER_PROTOCOL_DENIED": "This server does not support ADAM's bounded MCP 2025-11-25 tools protocol.",
    "INTERNET.PROVIDER_SCOPE_DENIED": "The requested tools are outside the declared provider scope.",
    "INTERNET.PROVIDER_ARGUMENTS_DENIED": "Arguments do not match the declared tool schema.",
    "INTERNET.FORM_DENIED": "This form requires unsupported, sensitive or cross-origin behavior.",
    "INTERNET.STALE_PAGE": "The page or form draft changed. Create a new preview.",
    "INTERNET.APPROVAL_REQUIRED": "Review a fresh action preview and reauthenticate before execution.",
    "INTERNET.CANCELLED": "External access was cancelled. A request already sent may still have taken effect.",

    "OPERATIONS.TIME_INVALID": "Choose a time within the next ten years, or at most one minute ago.",
    "OPERATIONS.ID_CONFLICT": "This retry has different reminder fields. Edit the reminder to begin a new request.",
    "OPERATIONS.QUIET_HOURS_INVALID": "Enter both quiet-hour times, or leave both blank.",
    "OPERATIONS.STORE_UNAVAILABLE": "The reminder store could not be opened. Local chat still works; preserve the operations directory before recovery.",
    "OPERATIONS.CAPACITY": "The reminder store reached its 500-job limit. Old completed jobs are pruned after 30 days.",
    "MESH.TLS_NOT_CONFIGURED": "Prepare trusted HTTPS with scripts/setup-mesh.ps1 before starting the Android listener.",
    "MESH.TLS_UNAVAILABLE": "The local HTTPS configuration could not be opened. Follow the mobile setup instructions; the listener is off.",
    "MESH.START_FAILED": "The listener could not start. Check the configured PC address and whether its port is already in use.",
    "MESH.NOT_PRIMARY": "This session is on another device. Return it to the PC before continuing here.",
    "VOICE.NOT_PRIMARY": "Speech is assigned to another device. Return the session to the PC to speak here.",
    "MESH.SESSION_BUSY": "Finish or stop the active response before handing this session to another device.",
    "MESH.SESSION_NOT_SHARED": "Share the selected session with this approved device before handing it over.",
    "MESH.IDENTITY_UNAVAILABLE": "The device registry or key could not be opened. Local chat still works; preserve the mesh directory before recovery.",
    "VOICE.ASSETS_MISSING":
      "Speech models are missing. Run scripts/setup-voice.ps1, then restart ADAM.",
    "VOICE.DISABLED":
      "Voice is disabled in this configuration. Text is available.",
    "VOICE.BUSY": "Speech processing is busy. Wait briefly and try again.",
    "VOICE.SPEAKER_ASSETS_MISSING":
      "Speaker models are missing. Run scripts/setup-speakers.ps1 and restart ADAM.",
    "VOICE.ENROLLMENT_DURATION":
      "Record 6–20 seconds of continuous speech for enrollment.",
    "VOICE.ENROLLMENT_MULTIPLE_SPEAKERS":
      "Enrollment needs one person speaking clearly, without overlap.",
    "VOICE.ENROLLMENT_INCONSISTENT":
      "Voice samples were inconsistent. Try again in a quiet room.",
    "VOICE.OWNER_ALREADY_ENROLLED":
      "Remove the existing owner template before enrolling a replacement.",
    "VOICE.SPEAKER_LIMIT":
      "Eight speaker templates are already saved. Remove one first.",
    "VOICE.TEMPLATE_UNAVAILABLE":
      "This voice template cannot be opened. Remove it and enroll again.",
    "VOICE.LANGUAGE_UNAVAILABLE":
      "This speech engine does not support that language. Choose Kokoro or English.",
    "VOICE.WINDOWS_VOICE_UNAVAILABLE":
      "No offline Windows English voice is available. Choose Kokoro or use text.",
    "VOICE.PROVIDER_FAILED":
      "Local speech processing failed. Try again or use text.",
    "AUTH.DENIED": "That passphrase was not accepted. Try again.",
    "AUTH.REQUIRED": "Your session expired. Unlock ADAM again.",
    "AUTH.ELEVATION_REQUIRED":
      "Re-enter your owner passphrase to open developer mode.",
    "AUTH.RATE_LIMITED":
      "Too many attempts. Wait a minute before trying again.",
    "AUTH.PASSPHRASE_LENGTH":
      "Use a passphrase between 12 and 1024 characters.",
    "AUTH.ALREADY_CONFIGURED":
      "An owner passphrase already exists. Sign in with it.",
    "RESOURCE.PRESSURE":
      "Your PC is short on free resources. Close an unused application and try again.",
    "RESOURCE.OOM":
      "The model ran out of memory. Free some memory, then reload it in developer mode.",
    "RESOURCE.RECOVERY_REQUIRED":
      "The model needs an explicit reload after an error.",
    "RESOURCE.COOLDOWN":
      "The model is cooling down after a failure. Wait briefly before reloading.",
    "MODEL.PORT_BUSY":
      "Another model server is using this port. Close its launcher before restarting the desktop service.",
    "MODEL.NOT_LOADED": "The model is unloaded. Reload it in developer mode.",
    "MODEL.UNAVAILABLE":
      "The model is unavailable. Check its status in settings.",
    "MODEL.TIMEOUT":
      "The model took too long. Your last turn was not saved; try a shorter request.",
    "SESSION.BUSY":
      "A response is already in progress. Stop it before starting another.",
    "CONTEXT.OVERFLOW":
      "This message is too large for the current model context. Try a shorter message or a new conversation.",
    "DESKTOP.BACKEND_STOPPED":
      "The local service stopped. Restart it to continue; saved data stays on this PC.",
    "DESKTOP.CONNECTION_LOST":
      "The local service connection was lost. Restart the service to reconnect.",
    "DESKTOP.STREAM_INTERRUPTED":
      "The response was interrupted. Partial output has not been saved as a completed turn.",
    "DESKTOP.SERVICE_MISSING":
      "The packaged service is missing. Repair or reinstall ADAM.",
    "DESKTOP.NATIVE_REQUIRED":
      "Open the installed ADAM desktop application to connect to your local service.",
    "DESKTOP.START_TIMEOUT":
      "The local service did not start in time. Check available memory and restart it.",
    "INPUT.INVALID": "Check the message fields and try again.",
  };
  return (
    known[code] ??
    (/^[A-Z][A-Z0-9_.]{1,99}$/.test(code)
      ? `The operation could not finish (${code}).`
      : "The operation could not finish. Try again.")
  );
}
export type Preferences = { avatar: boolean; reducedMotion: boolean };
export function readPreferences(
  value: string | null,
  systemReduced: boolean,
): Preferences {
  try {
    const parsed = JSON.parse(value ?? "{}");
    return {
      avatar: typeof parsed.avatar === "boolean" ? parsed.avatar : true,
      reducedMotion:
        typeof parsed.reducedMotion === "boolean"
          ? parsed.reducedMotion
          : systemReduced,
    };
  } catch {
    return { avatar: true, reducedMotion: systemReduced };
  }
}
