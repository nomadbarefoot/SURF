"""Contain caller-selected artifact paths to explicit writable roots."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from config import get_settings
from core.foundation import ValidationError


REPO_ROOT = Path(__file__).resolve().parent.parent


def configured_export_roots() -> tuple[Path, ...]:
    settings = get_settings()
    values = [settings.downloads_dir, settings.screenshots_dir, *settings.export_roots]
    roots: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        resolved = path.resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def is_allowed_export_path(path: Path, roots: Optional[Iterable[Path]] = None) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    for root in roots or configured_export_roots():
        try:
            resolved.relative_to(Path(root).resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def resolve_export_directory(value: str, *, create: bool = True) -> Path:
    if not value:
        raise ValidationError("output_dir", "Output directory is required")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve(strict=False)
    if not is_allowed_export_path(path):
        raise ValidationError(
            "output_dir",
            "Output directory is outside configured export roots",
            value,
        )
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValidationError("output_dir", f"Unable to create output directory: {exc}", value) from exc
    resolved = path.resolve(strict=False)
    if not is_allowed_export_path(resolved) or not resolved.is_dir():
        raise ValidationError("output_dir", "Output path is not an allowed directory", value)
    return resolved


def resolve_export_file(value: str, *, default_root: str) -> Path:
    settings = get_settings()
    default_value = getattr(settings, default_root)
    root = Path(default_value).expanduser()
    if not root.is_absolute():
        root = REPO_ROOT / root

    requested = Path(value).expanduser()
    if not requested.is_absolute() and requested.parent == Path("."):
        requested = root / requested.name
    elif not requested.is_absolute():
        requested = REPO_ROOT / requested
    requested = requested.resolve(strict=False)
    if not is_allowed_export_path(requested):
        raise ValidationError("path", "Artifact path is outside configured export roots", value)
    requested.parent.mkdir(parents=True, exist_ok=True)
    resolved = requested.resolve(strict=False)
    if not is_allowed_export_path(resolved):
        raise ValidationError("path", "Artifact path escapes configured export roots", value)
    return resolved
