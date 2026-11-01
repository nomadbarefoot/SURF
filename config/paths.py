"""Filesystem roots for SURF code assets and runtime data.

``CODE_ROOT`` holds bundled assets (config YAML, skills). ``surf_home()`` holds
mutable runtime data (browser profiles, downloads, caches). In a source
checkout or the Docker image they are the same directory, preserving the
historical ``./data`` layout. When installed as a package (``uvx``/``pipx``),
data moves to ``~/.surf`` so upgrades never wipe profiles or cookies.
``SURF_HOME`` overrides both cases.
"""

from __future__ import annotations

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent


def is_installed_package() -> bool:
    return any(part in {"site-packages", "dist-packages"} for part in CODE_ROOT.parts)


def surf_home() -> Path:
    override = os.getenv("SURF_HOME")
    if override:
        return Path(override).expanduser()
    if is_installed_package():
        return Path.home() / ".surf"
    return CODE_ROOT


def resolve_data_path(value: str | os.PathLike[str]) -> Path:
    """Resolve a configured data path; relative paths live under surf_home()."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else surf_home() / path
