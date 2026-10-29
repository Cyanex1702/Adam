"""Bounded, conversation-free diagnostics shared by desktop and source terminal."""

import hashlib
from typing import Any, cast

from adam import APP_VERSION
from adam.core.config import Settings

GUIDANCE = {
    "RESOURCE.GPU_TELEMETRY_UNAVAILABLE": (
        "Available video memory could not be verified for the selected GPU",
        "Keep CPU selected or check the NVIDIA driver and its memory readings. "
        "ADAM will not guess which adapter has enough memory.",
    ),
    "RESOURCE.VRAM_BUDGET": (
        "This model and context do not fit the available video memory",
        "Use CPU, choose a smaller model or context, or free GPU memory. A failed "
        "device change does not replace the saved selection.",
    ),
    "RESOURCE.VRAM_PRESSURE": (
        "Available video memory is below the safety margin",
        "Wait for other GPU work to finish or choose CPU. Other apps are never "
        "closed automatically.",
    ),
    "MODEL.GPU_UNAVAILABLE": (
        "The local inference runtime cannot find a Vulkan GPU",
        "Keep CPU selected or check the graphics driver and Vulkan runtime. A failed "
        "device change keeps the saved selection and attempts to restore the previous model.",
    ),
    "MODEL.DEVICE_EXTERNAL": (
        "Another application manages this model server",
        "Change the device in that application, or select an ADAM-managed model first.",
    ),
    "MODEL.LIFECYCLE_BUSY": (
        "The model is being used or changed",
        "Wait for loading or the current answer to finish before reloading, switching "
        "models or changing performance mode. Chat waits for a load automatically. "
        "The activity counters below identify what is running; restarting is not required.",
    ),
    "RESOURCE.QUEUE_TIMEOUT": (
        "The request waited too long for the model",
        "Check model activity below. Wait for loading or the current answer to finish, "
        "then retry. Stop an unwanted answer before changing the model.",
    ),
    "MODEL.LOAD_CANCELLED": (
        "Model loading was cancelled",
        "Use Retry loading model when ready. Conversations and memory were preserved.",
    ),
    "MODEL.TIMEOUT": (
        "The local model did not make reply progress in time",
        "Cold CPU prompt processing has a separate first-response wait. Once text starts, "
        "a stalled reply still times out. Check available RAM and CPU load, use Priority "
        "if appropriate, or choose a smaller approved model. Completed history is preserved.",
    ),
    "STORAGE.SCHEMA_MISMATCH": (
        "A database layout does not match its recorded version",
        "Preserve the profile and its journals. Check the database listed below. "
        "Do not delete it or edit migration records; a verified recovery copy is required.",
    ),
    "STORAGE.UNSUPPORTED_SCHEMA": (
        "A database version or migration record is unsupported",
        "Use the ADAM version that created this profile, or inspect a verified recovery copy. "
        "Do not reset the database or change its migration checksums.",
    ),
    "MODEL.REVIEW_CONTEXT_LIMIT": (
        "The question and review do not fit this model's context",
        "Use standard mode, shorten the question, or select an approved model with "
        "a larger context. ADAM will not drop required evidence to fit the review.",
    ),
    "MODEL.PROCESS_GUARD_FAILED": (
        "Windows could not protect the model's process lifetime",
        "The owned child was stopped. Restart ADAM and check endpoint security permissions. "
        "ADAM will not leave an unprotected inference server running.",
    ),
    "CONFIG.PERFORMANCE_INVALID": (
        "Saved performance preferences could not be read",
        "Preserve the config folder and restore a valid Eco or Priority preference. "
        "Your conversations do not need to be deleted.",
    ),
    "RESOURCE.MODEL_RAM_BUDGET": (
        "This model does not fit the currently available RAM",
        "Close another model session, free memory, or choose a smaller model. "
        "Priority mode cannot make an oversized model fit safely.",
    ),
    "MODEL.CONTEXT_MISMATCH": (
        "The running model server has a smaller context than this profile requests",
        "Use a matching model profile, or stop that server and reload ADAM's selected model.",
    ),
    "MODEL.IDENTITY_MISMATCH": (
        "The local server is serving a different model",
        "Select the matching model profile or stop the other server before reloading.",
    ),
    "STORAGE.BUSY": (
        "A database is currently locked",
        "Close the other ADAM copy and reconnect. Preserve journal files; "
        "never delete a live lock.",
    ),
    "STORAGE.ACCESS_DENIED": (
        "ADAM cannot read a profile database",
        "Check the selected folder's permissions. This is not evidence of database corruption.",
    ),
    "STORAGE.IO_FAILED": (
        "A profile file could not be read from storage",
        "Check drive availability and permissions. Preserve your data before recovery.",
    ),
    "RESOURCE.RAM_PRESSURE": (
        "Not enough available memory",
        "Close unused applications, select a smaller model, or retry after memory is available.",
    ),
    "RESOURCE.STORAGE_PRESSURE": (
        "The data drive is nearly full",
        "Free space on the data drive before retrying. Do not delete ADAM databases or journals.",
    ),
    "RESOURCE.TELEMETRY_UNAVAILABLE": (
        "Resource readings are unavailable",
        "Refresh diagnostics. Loading is paused until reliable memory and disk readings return.",
    ),
    "RESOURCE.OOM": (
        "Model allocation ran out of memory",
        "Free memory or choose a smaller model, then use Reload model.",
    ),
    "RESOURCE.PRESSURE": (
        "Model loading was blocked by resource checks",
        "Review the memory and disk checks below. Retry loading when they pass.",
    ),
    "MODEL.NOT_INSTALLED": (
        "The selected model or inference runtime is missing",
        (
            "Open Model library to locate an existing GGUF, or use Setup to "
            "download a supported model."
        ),
    ),
    "MODEL.PORT_BUSY": (
        "Another service is using the model port",
        (
            "Close the other ADAM session or configure a different local port. "
            "ADAM will not terminate another server."
        ),
    ),
    "MODEL.UNAVAILABLE": (
        "The configured model server is not responding",
        "Reload an ADAM-managed model, or start the configured external local server.",
    ),
    "MODEL.LOAD_FAILED": (
        "The inference process could not load this model",
        (
            "Check model/runtime compatibility and available memory, then "
            "retry or choose a different GGUF."
        ),
    ),
    "MODEL.LOAD_TIMEOUT": (
        "Model loading took too long",
        "Wait for disk activity to settle, then retry. A smaller model may load faster.",
    ),
    "MODEL.CONFIGURATION_INVALID": (
        "Saved model settings need review",
        (
            "Preserve the config folder and use the local recovery guide. Do "
            "not reset the catalog or delete your conversations."
        ),
    ),
    "CONFIG.INVALID": (
        "Application configuration could not be read",
        "Preserve the configuration and check its format using the local recovery guide.",
    ),
    "STORAGE.WAL_INVALID": (
        "A database journal could not be validated",
        (
            "Close all ADAM copies and preserve the database together with its "
            "WAL/SHM files before recovery."
        ),
    ),
    "STORAGE.INTEGRITY_FAILED": (
        "A database integrity check failed",
        (
            "Preserve the profile and use verified backup/restore recovery. "
            "Reinstallation alone will not repair stored data."
        ),
    ),
    "STORAGE.RECORD_INVALID": (
        "A stored record failed validation",
        "Preserve the profile and inspect an isolated copy using the recovery guide.",
    ),
    "BACKUP.PATH_DENIED": (
        "A profile file resolves outside its data folder",
        (
            "Check the selected profile location and Windows path redirection. "
            "Do not move or overwrite data without a verified backup."
        ),
    ),
    "DESKTOP.PROFILE_IN_USE": (
        "Another ADAM service has this profile open",
        (
            "Close the other ADAM desktop copy, then reconnect. Lock files are "
            "not safe to delete while a service runs."
        ),
    ),
    "DESKTOP.CONNECTION_LOST": (
        "The desktop cannot reach its local service",
        (
            "Reconnect once. If it fails again, copy this diagnostic report "
            "rather than repeatedly restarting."
        ),
    ),
}


def describe(code: str) -> dict[str, str]:
    title, action = GUIDANCE.get(
        code,
        (
            "A check needs attention",
            (
                "Keep this diagnostic code and follow the local recovery guide. "
                "Your data should be preserved."
            ),
        ),
    )
    return {"code": code, "title": title, "next_step": action}


def report(
    settings: Settings, manager: Any = None, issues: list[str] | None = None
) -> dict[str, Any]:
    from adam.compute.hardware import telemetry
    from adam.resilience.recovery import inspect

    resource = manager.observe() if manager else telemetry(settings.data_dir, gpu=False)
    storage = inspect(settings)
    codes = (
        list(issues or []) + list(resource.get("reasons", [])) + cast(list[str], storage["issues"])
    )
    if manager and manager.error:
        codes.append(manager.error)
    if manager and manager.last_health and manager.last_health.reason:
        codes.append(manager.last_health.reason)
    if manager and manager.controller and manager.controller.library.error:
        codes.append(manager.controller.library.error)
    identifier = settings.model.model_id
    if identifier not in {"qwen3-4b-instruct", "qwen3-4b-abliterated", "qwen3-8b"}:
        identifier = "custom-" + hashlib.sha256(identifier.encode()).hexdigest()[:12]
    return {
        "release": APP_VERSION,
        "report_format": 1,
        "profile_reference": hashlib.sha256(str(settings.data_dir.resolve()).encode()).hexdigest()[
            :12
        ],
        "issues": [describe(code) for code in sorted(set(codes))],
        "storage": {
            "mode": storage["mode"],
            "stores": storage["stores"],
            "schemas": storage["schemas"],
        },
        "resources": {
            key: resource.get(key)
            for key in (
                "sampled_at",
                "ram_available_bytes",
                "ram_total_bytes",
                "ram_used_percent",
                "disk_free_bytes",
                "mode",
                "limits",
                "gpus",
            )
        },
        "performance_mode": manager.config.mode if manager else settings.compute.mode,
        "model": {
            "id": identifier,
            "context_tokens": settings.model.context_limit,
            "output_tokens": settings.model.max_tokens,
            "first_token_timeout_seconds": settings.model.first_token_timeout_seconds,
            "stream_idle_timeout_seconds": settings.model.timeout_seconds,
            "lifecycle": manager.state if manager else "RECOVERY_READ_ONLY",
            "activity": manager.activity() if manager else None,
            "device": getattr(getattr(manager.delegate, "profile", None), "device", "external")
            if manager else "unavailable",
            "process": process_status(manager),
        },
        "privacy": (
            "No conversation text, credentials, personal filenames, usernames or network "
            "addresses included. Storage names are fixed application database names."
        ),
    }


def process_status(manager: Any) -> dict[str, Any]:
    from adam.compute.owned import OwnedLlamaProvider

    provider = manager.delegate if manager else None
    owned = provider if isinstance(provider, OwnedLlamaProvider) else None
    process = owned.process if owned else None
    return {
        "ownership": "adam" if owned else "external_or_unavailable",
        "running": bool(process and process.poll() is None),
        "pid": process.pid if process and process.poll() is None else None,
        "crash_cleanup": bool(owned and owned.guard),
        "source_tray_visible": bool(owned and owned.indicator and owned.indicator.available),
        "cpu_weight_repacking": owned.repack if owned else None,
        "microphone": "Model inference has no microphone capture capability",
    }
