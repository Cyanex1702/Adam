import os
from pathlib import Path


def mapped_profile_root(root: Path, anchors: list[str]) -> Path | None:
    """Recognize a Windows cache only when existing profile files resolve into it."""
    if os.name != "nt":
        return None
    packages = (root.parent / "Packages").resolve()
    mapped = None
    for relative in anchors:
        file = root / relative
        if not file.exists():
            continue
        if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
            return None
        actual = file.resolve()
        relative_depth = len(Path(relative).parts)
        if len(actual.parents) < relative_depth:
            return None
        candidate = actual.parents[relative_depth - 1]
        if candidate.parent.parent.parent.parent != packages:
            return None
        cache_suffix = tuple(part.casefold() for part in candidate.parts[-3:])
        if cache_suffix != ("localcache", "local", "adam"):
            return None
        if actual != candidate / relative:
            return None
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            return None
        if mapped is not None and mapped != candidate:
            return None
        mapped = candidate
    return mapped
