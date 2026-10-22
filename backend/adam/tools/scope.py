import hashlib
import stat
from pathlib import Path

from adam.core.privacy import contains_secret
from adam.tools.registry import ToolError


class FileScope:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path(".")

    def path(self, value: str, *, internal: bool = False) -> Path:
        candidate = self.root / value
        if ".." in Path(value).parts or (":" in value and not Path(value).is_absolute()):
            raise ToolError("TOOL.SCOPE_DENIED")
        try:
            relative = candidate.absolute().relative_to(self.root)
        except ValueError:
            raise ToolError("TOOL.SCOPE_DENIED") from None
        for part in relative.parts:
            stem = part.split(".")[0].upper()
            if (
                ":" in part
                or part.endswith((".", " "))
                or stem
                in {
                    "CON",
                    "PRN",
                    "AUX",
                    "NUL",
                    *[f"COM{i}" for i in range(10)],
                    *[f"LPT{i}" for i in range(10)],
                }
                or (part.startswith(".adam-") and not internal)
            ):
                raise ToolError("TOOL.SCOPE_DENIED")
        for parent in [candidate, *candidate.parents]:
            if parent.exists() or parent.is_symlink():
                info = parent.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
                    raise ToolError("TOOL.LINK_DENIED")
        return candidate

    def stamp(self, path: Path) -> str:
        if not path.exists():
            return "absent"
        info = path.stat()
        if path.is_dir():
            return f"directory:{info.st_dev}:{info.st_ino}"
        if not path.is_file() or info.st_nlink != 1 or info.st_size > 1024 * 1024:
            raise ToolError("TOOL.FILE_UNSUPPORTED")
        data = path.read_bytes()
        try:
            secret = contains_secret(data.decode("utf-8"))
        except UnicodeDecodeError:
            secret = False
        if secret:
            raise ToolError("TOOL.SECRET_FILE_DENIED")
        return f"file:{info.st_dev}:{info.st_ino}:{hashlib.sha256(data).hexdigest()}"

    def search(self, directory: str, query: str, limit: int) -> list[str]:
        folder = self.path(directory)
        if not folder.is_dir():
            raise ToolError("TOOL.DIRECTORY_REQUIRED")
        found: list[str] = []
        pending = [(folder, 0)]
        visited = 0
        while pending and visited < 5000 and len(found) < limit:
            current, depth = pending.pop()
            for child in sorted(current.iterdir()):
                visited += 1
                relative = str(child.relative_to(self.root))
                try:
                    safe = self.path(relative)
                    self.stamp(safe)
                except ToolError:
                    continue
                if safe.is_dir() and depth < 16:
                    pending.append((safe, depth + 1))
                elif safe.is_file() and query.casefold() in child.name.casefold():
                    found.append(relative)
                if visited >= 5000 or len(found) >= limit:
                    break
        return found
