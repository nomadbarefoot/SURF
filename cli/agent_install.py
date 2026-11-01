"""Register SURF as an MCP server with the AI agents installed on this machine.

``surf-mcp install`` detects supported agents (or takes ``--client``), then
adds a stdio server entry to each one's user-level ("global") config:

* agents with a dependable CLI (Claude Code, Codex) are configured through it;
* JSON/YAML-config agents get a merge that touches only SURF's entry, written
  atomically after a one-time ``.surf-backup`` copy;
* a config that cannot be parsed safely (e.g. JSON with comments) is left
  alone and a paste-ready snippet is printed instead.

Existing entries are never replaced without ``--force``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_SOURCE = "git+https://github.com/nomadbarefoot/SURF"
CODE_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Server definition
# ---------------------------------------------------------------------------


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)

    @property
    def argv(self) -> list[str]:
        return [self.command, *self.args]


def _is_installed_package() -> bool:
    return any(part in {"site-packages", "dist-packages"} for part in CODE_ROOT.parts)


def build_spec(
    *,
    name: str = "surf",
    profile: str = "web",
    extras: str = "",
    source: str = DEFAULT_SOURCE,
    env: Optional[dict[str, str]] = None,
    mode: str = "auto",
) -> ServerSpec:
    """Return how agents should launch SURF.

    ``uvx`` mode (default for installed packages) is portable and upgrades
    with ``uvx --refresh``. ``local`` mode (default in a source checkout)
    points at this checkout's interpreter, so local edits apply.
    """
    if mode == "auto":
        mode = "uvx" if _is_installed_package() else "local"
    tail = ["--profile", profile]
    if mode == "uvx":
        package = f"surf-web[{extras}] @ {source}" if extras else source
        return ServerSpec(name, "uvx", ["--from", package, "surf-mcp", *tail], dict(env or {}))
    venv_python = CODE_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    return ServerSpec(
        name, python, [str(CODE_ROOT / "surfctl.py"), "mcp", *tail], dict(env or {})
    )


# ---------------------------------------------------------------------------
# Results and file helpers
# ---------------------------------------------------------------------------


@dataclass
class Result:
    client: str
    status: str  # installed | exists | removed | absent | skipped | manual | failed | planned
    detail: str = ""
    snippet: str = ""


class UnsafeConfig(Exception):
    """The config exists but cannot be edited without risking user content."""


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _app_support(*parts: str) -> Path:
    """Per-OS application config directory."""
    if sys.platform == "darwin":
        return _home().joinpath("Library", "Application Support", *parts)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming")).joinpath(*parts)
    return Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config")).joinpath(*parts)


def _backup_once(path: Path) -> None:
    backup = path.with_name(path.name + ".surf-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup_once(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UnsafeConfig(f"{path} is not plain JSON (comments?): {exc.msg}") from exc
    if not isinstance(data, dict):
        raise UnsafeConfig(f"{path} does not contain a JSON object")
    return data


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


class Client:
    key = ""
    label = ""

    def detected(self) -> bool:
        raise NotImplementedError

    def has(self, spec: ServerSpec) -> bool:
        raise NotImplementedError

    def add(self, spec: ServerSpec) -> None:
        raise NotImplementedError

    def remove(self, spec: ServerSpec) -> bool:
        raise NotImplementedError

    def snippet(self, spec: ServerSpec) -> str:
        raise NotImplementedError

    def where(self) -> str:
        return ""


class JsonClient(Client):
    """Agents whose MCP servers live in one JSON object inside a file."""

    section = "mcpServers"

    def path(self) -> Path:
        raise NotImplementedError

    def marker(self) -> Path:
        """A path whose existence means the agent is installed."""
        return self.path().parent

    def detected(self) -> bool:
        return self.path().exists() or self.marker().exists()

    def where(self) -> str:
        return str(self.path())

    def entry(self, spec: ServerSpec) -> dict[str, Any]:
        entry: dict[str, Any] = {"command": spec.command, "args": spec.args}
        if spec.env:
            entry["env"] = spec.env
        return entry

    def _servers(self, data: dict[str, Any]) -> dict[str, Any]:
        servers = data.get(self.section)
        if servers is None:
            return {}
        if not isinstance(servers, dict):
            raise UnsafeConfig(f"{self.path()}: '{self.section}' is not an object")
        return servers

    def has(self, spec: ServerSpec) -> bool:
        return spec.name in self._servers(_load_json(self.path()))

    def add(self, spec: ServerSpec) -> None:
        data = _load_json(self.path())
        servers = dict(self._servers(data))
        servers[spec.name] = self.entry(spec)
        data[self.section] = servers
        _atomic_write(self.path(), json.dumps(data, indent=2) + "\n")

    def remove(self, spec: ServerSpec) -> bool:
        data = _load_json(self.path())
        servers = dict(self._servers(data))
        if spec.name not in servers:
            return False
        del servers[spec.name]
        data[self.section] = servers
        _atomic_write(self.path(), json.dumps(data, indent=2) + "\n")
        return True

    def snippet(self, spec: ServerSpec) -> str:
        return json.dumps({self.section: {spec.name: self.entry(spec)}}, indent=2)


class Cursor(JsonClient):
    key, label = "cursor", "Cursor"

    def path(self) -> Path:
        return _home() / ".cursor" / "mcp.json"


class ClaudeDesktop(JsonClient):
    key, label = "claude-desktop", "Claude Desktop"

    def path(self) -> Path:
        return _app_support("Claude", "claude_desktop_config.json")


class Windsurf(JsonClient):
    key, label = "windsurf", "Windsurf"

    def path(self) -> Path:
        return _home() / ".codeium" / "windsurf" / "mcp_config.json"


class Gemini(JsonClient):
    key, label = "gemini", "Gemini CLI"

    def path(self) -> Path:
        return _home() / ".gemini" / "settings.json"

    def detected(self) -> bool:
        return shutil.which("gemini") is not None or self.path().parent.exists()


class VSCode(JsonClient):
    key, label = "vscode", "VS Code (Copilot agent mode)"
    section = "servers"

    def path(self) -> Path:
        return _app_support("Code", "User", "mcp.json")

    def entry(self, spec: ServerSpec) -> dict[str, Any]:
        return {"type": "stdio", **super().entry(spec)}


class OpenCode(JsonClient):
    key, label = "opencode", "OpenCode"
    section = "mcp"

    def path(self) -> Path:
        base = Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config"))
        return base / "opencode" / "opencode.json"

    def detected(self) -> bool:
        return shutil.which("opencode") is not None or self.path().parent.exists()

    def entry(self, spec: ServerSpec) -> dict[str, Any]:
        entry: dict[str, Any] = {"type": "local", "command": spec.argv, "enabled": True}
        if spec.env:
            entry["environment"] = spec.env
        return entry


class Hermes(Client):
    """Hermes Agent: ``mcp_servers`` in ~/.hermes/config.yaml.

    Edited textually so comments and formatting elsewhere survive; PyYAML is
    used only to validate before and after.
    """

    key, label = "hermes", "Hermes Agent"

    def path(self) -> Path:
        return _home() / ".hermes" / "config.yaml"

    def where(self) -> str:
        return str(self.path())

    def detected(self) -> bool:
        return shutil.which("hermes") is not None or self.path().exists()

    def _load(self) -> tuple[str, dict[str, Any]]:
        import yaml

        text = self.path().read_text(encoding="utf-8") if self.path().exists() else ""
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise UnsafeConfig(f"{self.path()} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise UnsafeConfig(f"{self.path()} is not a YAML mapping")
        servers = data.get("mcp_servers")
        if servers is not None and not isinstance(servers, dict):
            raise UnsafeConfig(f"{self.path()}: mcp_servers is not a mapping")
        return text, data

    def has(self, spec: ServerSpec) -> bool:
        _, data = self._load()
        return spec.name in (data.get("mcp_servers") or {})

    def _block(self, spec: ServerSpec, indent: str) -> list[str]:
        lines = [
            f"{indent}{spec.name}:",
            f"{indent}  command: {json.dumps(spec.command)}",
            f"{indent}  args: {json.dumps(spec.args)}",
        ]
        if spec.env:
            lines.append(f"{indent}  env:")
            lines.extend(f"{indent}    {k}: {json.dumps(v)}" for k, v in spec.env.items())
        return lines

    def add(self, spec: ServerSpec) -> None:
        import yaml

        text, data = self._load()
        lines = text.splitlines()
        if "mcp_servers" not in data:
            if lines and lines[-1].strip():
                lines.append("")
            lines += ["mcp_servers:", *self._block(spec, "  ")]
        else:
            starts = [i for i, line in enumerate(lines) if line.rstrip() == "mcp_servers:"]
            if len(starts) != 1:
                raise UnsafeConfig(f"{self.path()}: mcp_servers is not a simple block")
            start = starts[0]
            child_indent = "  "
            for line in lines[start + 1:]:
                if line.strip() and not line.lstrip().startswith("#"):
                    stripped = len(line) - len(line.lstrip(" "))
                    if stripped:
                        child_indent = " " * stripped
                    break
            lines[start + 1:start + 1] = self._block(spec, child_indent)
        new_text = "\n".join(lines) + "\n"
        parsed = yaml.safe_load(new_text) or {}
        if spec.name not in (parsed.get("mcp_servers") or {}):
            raise UnsafeConfig(f"{self.path()}: could not insert entry safely")
        _atomic_write(self.path(), new_text)

    def remove(self, spec: ServerSpec) -> bool:
        if not self.has(spec):
            return False
        raise UnsafeConfig(
            f"remove '{spec.name}' from mcp_servers in {self.path()} by hand "
            "(automatic removal is not supported for YAML)"
        )

    def snippet(self, spec: ServerSpec) -> str:
        return "\n".join(["mcp_servers:", *self._block(spec, "  ")])


class CliClient(Client):
    """Agents configured through their own CLI."""

    binary = ""

    def detected(self) -> bool:
        return shutil.which(self.binary) is not None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.binary, *args], capture_output=True, text=True, timeout=60
        )

    def _check(self, proc: subprocess.CompletedProcess) -> None:
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-300:] or "command failed")


class ClaudeCode(CliClient):
    key, label, binary = "claude-code", "Claude Code", "claude"

    def where(self) -> str:
        return "claude mcp (user scope)"

    def has(self, spec: ServerSpec) -> bool:
        path = _home() / ".claude.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self._run(["mcp", "get", spec.name]).returncode == 0
        return spec.name in (data.get("mcpServers") or {})

    def add(self, spec: ServerSpec) -> None:
        env_args = [arg for k, v in spec.env.items() for arg in ("-e", f"{k}={v}")]
        self._check(self._run(["mcp", "add", "-s", "user", spec.name, *env_args, "--", *spec.argv]))

    def remove(self, spec: ServerSpec) -> bool:
        if not self.has(spec):
            return False
        self._check(self._run(["mcp", "remove", "-s", "user", spec.name]))
        return True

    def snippet(self, spec: ServerSpec) -> str:
        env_args = " ".join(f"-e {k}={v}" for k, v in spec.env.items())
        return " ".join(
            part for part in ["claude mcp add -s user", spec.name, env_args, "--", _shell_join(spec.argv)] if part
        )


class Codex(CliClient):
    key, label, binary = "codex", "Codex CLI", "codex"

    def path(self) -> Path:
        return Path(os.environ.get("CODEX_HOME", _home() / ".codex")) / "config.toml"

    def where(self) -> str:
        return str(self.path())

    def detected(self) -> bool:
        return super().detected() or self.path().exists()

    def has(self, spec: ServerSpec) -> bool:
        import tomllib

        if not self.path().exists():
            return False
        try:
            data = tomllib.loads(self.path().read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise UnsafeConfig(f"{self.path()} is not valid TOML: {exc}") from exc
        return spec.name in (data.get("mcp_servers") or {})

    def add(self, spec: ServerSpec) -> None:
        if shutil.which(self.binary):
            env_args = [arg for k, v in spec.env.items() for arg in ("--env", f"{k}={v}")]
            self._check(self._run(["mcp", "add", spec.name, *env_args, "--", *spec.argv]))
            return
        # No CLI: appending a new table to TOML is always valid.
        text = self.path().read_text(encoding="utf-8") if self.path().exists() else ""
        _atomic_write(self.path(), text.rstrip("\n") + ("\n\n" if text.strip() else "") + self.snippet(spec) + "\n")

    def remove(self, spec: ServerSpec) -> bool:
        if not self.has(spec):
            return False
        if not shutil.which(self.binary):
            raise UnsafeConfig(f"remove [mcp_servers.{spec.name}] from {self.path()} by hand")
        self._check(self._run(["mcp", "remove", spec.name]))
        return True

    def snippet(self, spec: ServerSpec) -> str:
        lines = [
            f"[mcp_servers.{spec.name}]",
            f"command = {json.dumps(spec.command)}",
            f"args = {json.dumps(spec.args)}",
        ]
        if spec.env:
            lines.append(f"[mcp_servers.{spec.name}.env]")
            lines.extend(f"{k} = {json.dumps(v)}" for k, v in spec.env.items())
        return "\n".join(lines)


def _shell_join(argv: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(arg) for arg in argv)


CLIENTS: dict[str, Callable[[], Client]] = {
    cls.key: cls
    for cls in (ClaudeCode, Codex, Cursor, ClaudeDesktop, VSCode, Gemini, Windsurf, OpenCode, Hermes)
}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def select_clients(names: Optional[str]) -> tuple[list[Client], bool]:
    """Return (clients, explicit). Default: every detected client."""
    if not names:
        return [factory() for factory in CLIENTS.values()], False
    keys = list(CLIENTS) if names.strip() == "all" else [n.strip() for n in names.split(",") if n.strip()]
    unknown = [k for k in keys if k not in CLIENTS]
    if unknown:
        raise ValueError(f"unknown client(s): {', '.join(unknown)} (choose from {', '.join(CLIENTS)}, all)")
    return [CLIENTS[k]() for k in keys], True


def install(
    spec: ServerSpec,
    clients: list[Client],
    *,
    explicit: bool,
    force: bool = False,
    dry_run: bool = False,
) -> list[Result]:
    results = []
    for client in clients:
        if not explicit and not client.detected():
            results.append(Result(client.label, "absent", "not detected"))
            continue
        try:
            if client.has(spec):
                if not force:
                    results.append(Result(client.label, "exists", f"'{spec.name}' already configured; --force replaces it"))
                    continue
                if not dry_run:
                    client.remove(spec)
            if dry_run:
                results.append(Result(client.label, "planned", client.where(), client.snippet(spec)))
                continue
            client.add(spec)
            results.append(Result(client.label, "installed", client.where()))
        except UnsafeConfig as exc:
            results.append(Result(client.label, "manual", str(exc), client.snippet(spec)))
        except Exception as exc:  # CLI failure, permissions, ...
            results.append(Result(client.label, "failed", str(exc), client.snippet(spec)))
    return results


def uninstall(spec: ServerSpec, clients: list[Client], *, explicit: bool, dry_run: bool = False) -> list[Result]:
    results = []
    for client in clients:
        if not explicit and not client.detected():
            results.append(Result(client.label, "absent", "not detected"))
            continue
        try:
            if not client.has(spec):
                results.append(Result(client.label, "skipped", f"no '{spec.name}' entry"))
            elif dry_run:
                results.append(Result(client.label, "planned", f"would remove from {client.where()}"))
            else:
                client.remove(spec)
                results.append(Result(client.label, "removed", client.where()))
        except UnsafeConfig as exc:
            results.append(Result(client.label, "manual", str(exc)))
        except Exception as exc:
            results.append(Result(client.label, "failed", str(exc)))
    return results


def render(results: list[Result], spec: ServerSpec) -> str:
    """YAML-style report: readable for people, parseable for agents."""
    lines = [
        "server:",
        f"  name: {spec.name}",
        f"  command: {json.dumps(spec.argv)}",
        "clients:",
    ]
    for r in results:
        lines.append(f"  - client: {r.client}")
        lines.append(f"    status: {r.status}")
        if r.detail:
            lines.append(f"    detail: {json.dumps(r.detail)}")
        if r.snippet:
            lines.append("    snippet: |")
            lines.extend(f"      {line}" for line in r.snippet.splitlines())
    if any(r.status == "installed" for r in results):
        lines.append("next: restart the agent(s) above so they load SURF")
    if not any(r.status not in {"absent"} for r in results):
        lines.append("next: no supported agent detected; pass --client (see --help) or paste a snippet")
    return "\n".join(lines)


def add_arguments(parser) -> None:
    parser.add_argument(
        "--client",
        help=f"Comma list of agents to configure, or 'all'. Default: every detected agent. Choices: {', '.join(CLIENTS)}",
    )
    parser.add_argument("--profile", default="web", help="Tool profile(s) the agent gets, e.g. web,browse or all")
    parser.add_argument("--name", default="surf", help="MCP server name (default: surf)")
    parser.add_argument("--extras", default="", help="Package extras for uvx mode: youtube, docs, or all")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="Package source for uvx mode")
    parser.add_argument("--mode", choices=("auto", "uvx", "local"), default="auto",
                        help="uvx: portable launcher; local: this checkout's Python (auto picks)")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                        help="Environment variable for the server (repeatable)")
    parser.add_argument("--force", action="store_true", help="Replace an existing entry with the same name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")


def run(args, *, remove: bool = False) -> int:
    env: dict[str, str] = {}
    for item in args.env:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise SystemExit(f"--env expects KEY=VALUE, got {item!r}")
        env[key] = value
    if remove:
        spec = ServerSpec(args.name, "", [], {})
    else:
        from surfctl import parse_profiles

        profile = ",".join(parse_profiles(args.profile))
        spec = build_spec(
            name=args.name, profile=profile, extras=args.extras,
            source=args.source, env=env, mode=args.mode,
        )
    try:
        clients, explicit = select_clients(args.client)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if remove:
        results = uninstall(spec, clients, explicit=explicit, dry_run=args.dry_run)
    else:
        if not args.dry_run:
            ok, message = prepare(spec)
            print(f"prepare: {message}", file=sys.stderr)
            if not ok:
                print(render([Result("all", "failed", message)], spec))
                return 1
        results = install(spec, clients, explicit=explicit, force=args.force, dry_run=args.dry_run)
    print(render(results, spec))
    return 1 if any(r.status == "failed" for r in results) else 0


def prepare(spec: ServerSpec) -> tuple[bool, str]:
    """Run the configured command once so agents' first launch is fast.

    A cold ``uvx`` install downloads SURF and its dependencies, which can take
    longer than an agent's MCP connect timeout (e.g. 30 s in Claude Code).
    """
    import time

    if shutil.which(spec.command) is None and not Path(spec.command).exists():
        hint = " (install uv: https://docs.astral.sh/uv/)" if spec.command == "uvx" else ""
        return False, f"'{spec.command}' not found on PATH{hint}"
    probe = [*spec.argv[: spec.argv.index("--profile")], "--help"] if "--profile" in spec.argv else [*spec.argv, "--help"]
    started = time.monotonic()
    try:
        proc = subprocess.run(probe, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return False, "timed out preparing the SURF package"
    if proc.returncode != 0:
        return False, f"launch check failed: {(proc.stderr or proc.stdout).strip()[-300:]}"
    return True, f"SURF launches OK ({time.monotonic() - started:.1f}s)"
