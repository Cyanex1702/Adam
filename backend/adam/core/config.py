import json
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from adam.compute.contracts import ComputeConfig
from adam.core.contracts import Contract
from adam.observability.service import TraceConfig
from adam.resilience.contracts import BackupConfig
from adam.voice.contracts import VoiceConfig


def resolve_data_dir(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    if values.get("ADAM_DATA_DIR"):
        return canonical_profile_dir(Path(values["ADAM_DATA_DIR"]))
    if os.name == "nt":
        base = Path(values.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(values.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return canonical_profile_dir(base / "ADAM")


def canonical_profile_dir(path: Path) -> Path:
    """Bind a Windows virtualized profile to the files already backing it.

    Only the known Store-host mapping is accepted, and only when every existing
    private anchor agrees. Mixed profiles stay unmodified and fail strict scope
    inspection. This never selects the public model cache merely because it exists.
    """
    root = path.expanduser().resolve()
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    if os.name != "nt" or root != (local / "ADAM").resolve():
        return root
    cached = local / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/ADAM"
    if cached.is_symlink() or (hasattr(cached, "is_junction") and cached.is_junction()):
        return root
    anchors = [
        "runtime.sqlite3",
        "security/auth.sqlite3",
        "security/vault.sqlite3",
        "actions.sqlite3",
        "tasks.sqlite3",
        "config/model-catalog.json",
        "config/model-selection.json",
        "config/restored-settings.json",
        "config/performance.json",
        "config/model-library.json",
        "operations/jobs.sqlite3",
        "mesh/registry.sqlite3",
        "voice/speakers.sqlite3",
        "identity/identity.yaml",
        "identity/personality.yaml",
        "identity/communication.yaml",
        "identity/epistemics.yaml",
    ]
    resolved = []
    for name in anchors:
        file = root / name
        if file.exists():
            if file.is_symlink() or (hasattr(file, "is_junction") and file.is_junction()):
                return root
            resolved.append((file.resolve(), (cached / name).resolve()))
    if resolved and all(
        actual == expected and actual.is_relative_to(cached.resolve())
        for actual, expected in resolved
    ):
        return cached.resolve()
    return root


def resolve_embedding_dir(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    base = resolve_data_dir({key: value for key, value in values.items() if key != "ADAM_DATA_DIR"})
    primary = base / "models" / "multilingual-e5-small"
    # Store-hosted Codex and ordinary PowerShell can see different LocalAppData views.
    # Reuse only public model assets; never redirect personal runtime data here.
    cached = (
        base.parent
        / "Packages"
        / "OpenAI.Codex_2p2nqsd0c76g0"
        / "LocalCache"
        / "Local"
        / "ADAM"
        / "models"
        / "multilingual-e5-small"
    )
    if (
        os.name == "nt"
        and not (primary / "model.onnx").is_file()
        and all((cached / name).is_file() for name in ["model.onnx", "tokenizer.json"])
    ):
        return cached
    return primary


class FeatureFlags(Contract):
    text: bool = True
    voice: bool = False
    speaker_id: bool = False
    spatial_audio: bool = False
    vision: bool = False
    browser_control: bool = False
    proactive_mode: bool = False
    mobile_mesh: bool = False

    @model_validator(mode="after")
    def reject_unimplemented(self) -> "FeatureFlags":
        if self.speaker_id and not self.voice:
            raise ValueError("Speaker recognition requires voice")
        if any(
            value
            for name, value in self.model_dump().items()
            if name not in {"text", "voice", "speaker_id", "mobile_mesh"}
        ):
            raise ValueError("This capability is not implemented")
        return self


class ModelConfig(Contract):
    provider: str = "llama_cpp"
    base_url: str = "http://127.0.0.1:8080"
    model_id: str = "qwen3-8b"
    display_name: str = "Qwen3-8B"
    quantization: str = "Q4_K_M"
    languages: list[str] = Field(default_factory=lambda: ["en"])
    context_limit: int = Field(default=8192, ge=512)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    first_token_timeout_seconds: float = Field(default=300, gt=0, le=600)
    temperature: float = Field(default=0.6, ge=0, le=2)
    seed: int | None = None
    tools: bool = False
    reasoning: bool = False
    json_output: bool = False

    @field_validator("provider")
    @classmethod
    def known_provider(cls, value: str) -> str:
        if value != "llama_cpp":
            raise ValueError("Only llama_cpp is installed; register future adapters explicitly")
        return value

    @field_validator("base_url")
    @classmethod
    def local_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Model URL must be a loopback HTTP origin without credentials")
        return value.rstrip("/")


class KnowledgeConfig(Contract):
    allowed_roots: list[Path] = Field(default_factory=lambda: [Path.cwd()])
    max_file_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    chunk_chars: int = Field(default=1000, ge=200, le=2000)
    enabled: bool = True
    embedding_dir: Path = Field(default_factory=lambda: resolve_embedding_dir())
    embedding_threads: int = Field(default=2, ge=1, le=4)


class Settings(Contract):
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    compute: ComputeConfig = Field(default_factory=ComputeConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    tracing: TraceConfig = Field(default_factory=TraceConfig)
    data_dir: Path = Field(default_factory=resolve_data_dir)
    identity_dir: Path | None = None
    model: ModelConfig = Field(default_factory=ModelConfig)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    max_sessions: int = Field(default=32, ge=1, le=1024)
    recent_turns: int = Field(default=8, ge=1, le=64)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    consolidation_interval_seconds: float = Field(default=300, ge=10, le=86400)
    vault_enabled: bool = True
    vault_backend: Literal["auto", "dpapi", "fernet"] = "auto"

    @field_validator("data_dir", mode="after")
    @classmethod
    def bind_existing_profile(cls, value: Path) -> Path:
        return canonical_profile_dir(value)


def load_settings(
    config_path: Path | None = None, env: Mapping[str, str] | None = None
) -> Settings:
    """Precedence: defaults < explicit user TOML < process environment."""
    values = os.environ if env is None else env
    if config_path is None and values.get("ADAM_CONFIG"):
        config_path = Path(values["ADAM_CONFIG"])
    data: dict[str, object] = {}
    if config_path is not None:
        with config_path.open("rb") as stream:
            data = tomllib.load(stream)
    selected_root = (
        resolve_data_dir(values)
        if "ADAM_DATA_DIR" in values or "data_dir" not in data
        else Path(str(data["data_dir"])).expanduser().resolve()
    )
    restored = selected_root / "config" / "restored-settings.json"
    if restored.exists():
        if restored.stat().st_size > 65536 or restored.is_symlink():
            raise ValueError("CONFIG.INVALID")
        saved = Settings.model_validate_json(restored.read_bytes()).model_dump(mode="json")
        for name, value in data.items():
            if isinstance(saved.get(name), dict) and isinstance(value, dict):
                saved[name].update(value)
            else:
                saved[name] = value
        data = saved
    model = dict(data.get("model", {}))  # type: ignore[call-overload]
    selection = selected_root / "config/model-selection.json"
    if selection.exists():
        if selection.stat().st_size > 65536 or any(
            path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
            for path in [selection, *selection.parents]
        ):
            raise ValueError("MODEL.SELECTION_INVALID")
        chosen = json.loads(selection.read_bytes())
        if set(chosen) != {"format", "model"} or chosen["format"] != 1:
            raise ValueError("MODEL.SELECTION_INVALID")
        model = ModelConfig.model_validate(chosen["model"]).model_dump()
    for key, name in {"ADAM_MODEL_URL": "base_url", "ADAM_MODEL_ID": "model_id"}.items():
        if key in values:
            model[name] = values[key]
    data["model"] = model
    if "ADAM_DATA_DIR" in values or "data_dir" not in data:
        data["data_dir"] = resolve_data_dir(values)
    if values.get("ADAM_IDENTITY_DIR"):
        data["identity_dir"] = Path(values["ADAM_IDENTITY_DIR"])
    flags = dict(data.get("features", {}))  # type: ignore[call-overload]
    if "ADAM_TEXT_ENABLED" in values:
        value = values["ADAM_TEXT_ENABLED"].lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError("ADAM_TEXT_ENABLED must be true/false or 1/0")
        flags["text"] = value in {"true", "1"}
    data["features"] = flags
    settings = Settings.model_validate(data)
    settings.data_dir = settings.data_dir.expanduser().resolve()
    return resolve_catalog_settings(settings)


def resolve_catalog_settings(settings: Settings) -> Settings:
    """Recover legacy catalog defaults without rewriting a profile or changing models.

    Older launchers wrote a catalog but no selection receipt. Packaged TOML defaults
    can differ in context/sampling/display fields. In that case retain the saved
    default only for the same model identity and local endpoint. Explicit selection
    receipts and incompatible identities still require strict validation.
    """
    from adam.compute.catalog import config_digest, read_catalog

    if (settings.data_dir / "config/model-selection.json").exists():
        return settings
    try:
        from adam.resilience.archive import scoped

        path = scoped(settings.data_dir, "config/model-catalog.json")
        if not path.exists():
            return settings
        catalog = read_catalog(path)
        if any(
            config_digest(item.model) == config_digest(settings.model)
            for item in catalog.profiles.values()
        ):
            return settings
        saved = catalog.profiles[catalog.default_id].model
        identity = ("provider", "model_id", "base_url", "quantization")
        if all(getattr(saved, key) == getattr(settings.model, key) for key in identity):
            return settings.model_copy(update={"model": saved.model_copy(deep=True)})
    except (ValueError, OSError):
        pass  # Inspection reports invalid metadata; never reset it here.
    return settings
