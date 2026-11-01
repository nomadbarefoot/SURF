"""surf-mcp install: agent detection and config merging (no real agent CLIs)."""

import json
import tomllib

import pytest
import yaml

from cli import agent_install as ai


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)  # no agent CLIs
    return tmp_path


@pytest.fixture
def spec():
    return ai.build_spec(profile="web,browse", mode="uvx", env={"K": "v"})


def _run(spec, keys, **kw):
    clients, explicit = ai.select_clients(keys)
    return {r.client: r for r in ai.install(spec, clients, explicit=explicit, **kw)}


def test_uvx_spec_and_extras():
    plain = ai.build_spec(mode="uvx")
    assert plain.argv == ["uvx", "--from", ai.DEFAULT_SOURCE, "surf-mcp", "--profile", "web"]
    extra = ai.build_spec(mode="uvx", extras="all")
    assert extra.args[1] == f"surf-web[all] @ {ai.DEFAULT_SOURCE}"


def test_local_spec_points_at_checkout():
    local = ai.build_spec(mode="local", profile="all")
    assert local.args[-3:] == ["mcp", "--profile", "all"]
    assert local.args[0].endswith("surfctl.py")


def test_detected_only_by_default(home, spec):
    (home / ".cursor").mkdir()
    results = _run(spec, None)
    assert results["Cursor"].status == "installed"
    assert results["Windsurf"].status == "absent"
    assert results["Claude Code"].status == "absent"


def test_json_merge_preserves_other_servers_and_backs_up(home, spec):
    path = home / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": 1}))
    assert _run(spec, "cursor")["Cursor"].status == "installed"
    data = json.loads(path.read_text())
    assert set(data["mcpServers"]) == {"other", "surf"}
    assert data["keep"] == 1
    assert data["mcpServers"]["surf"] == {"command": "uvx", "args": spec.args, "env": {"K": "v"}}
    assert json.loads((path.parent / "mcp.json.surf-backup").read_text())["mcpServers"] == {"other": {"command": "x"}}


def test_existing_entry_needs_force(home, spec):
    path = home / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"surf": {"command": "old"}}}))
    assert _run(spec, "cursor")["Cursor"].status == "exists"
    assert json.loads(path.read_text())["mcpServers"]["surf"] == {"command": "old"}
    assert _run(spec, "cursor", force=True)["Cursor"].status == "installed"
    assert json.loads(path.read_text())["mcpServers"]["surf"]["command"] == "uvx"


def test_dry_run_writes_nothing(home, spec):
    result = _run(spec, "cursor,gemini", dry_run=True)
    assert {r.status for r in result.values()} == {"planned"}
    assert not (home / ".cursor").exists() and not (home / ".gemini").exists()


def test_jsonc_config_falls_back_to_snippet(home, spec):
    path = ai.VSCode().path()
    path.parent.mkdir(parents=True)
    original = '{\n  // comment\n  "servers": {}\n}\n'
    path.write_text(original)
    result = _run(spec, "vscode")["VS Code (Copilot agent mode)"]
    assert result.status == "manual"
    assert '"type": "stdio"' in result.snippet
    assert path.read_text() == original


def test_client_specific_shapes(home, spec):
    _run(spec, "vscode,opencode,claude-desktop,windsurf,gemini")
    vscode = json.loads(ai.VSCode().path().read_text())["servers"]["surf"]
    assert vscode["type"] == "stdio" and vscode["command"] == "uvx"
    opencode = json.loads(ai.OpenCode().path().read_text())["mcp"]["surf"]
    assert opencode == {"type": "local", "command": spec.argv, "enabled": True, "environment": {"K": "v"}}
    for client in (ai.ClaudeDesktop(), ai.Windsurf(), ai.Gemini()):
        assert json.loads(client.path().read_text())["mcpServers"]["surf"]["args"] == spec.args


def test_hermes_yaml_insert_keeps_comments_and_servers(home, spec):
    path = home / ".hermes" / "config.yaml"
    path.parent.mkdir()
    path.write_text(
        "# top comment\nmodel: m  # inline\n\nmcp_servers:\n    github:\n        command: npx\n\nother: 1\n"
    )
    assert _run(spec, "hermes")["Hermes Agent"].status == "installed"
    text = path.read_text()
    assert "# top comment" in text and "# inline" in text
    data = yaml.safe_load(text)
    assert set(data["mcp_servers"]) == {"github", "surf"}
    assert data["mcp_servers"]["surf"] == {"command": "uvx", "args": spec.args, "env": {"K": "v"}}
    assert data["other"] == 1
    assert _run(spec, "hermes")["Hermes Agent"].status == "exists"


def test_hermes_creates_section_when_missing(home, spec):
    path = home / ".hermes" / "config.yaml"
    path.parent.mkdir()
    path.write_text("model: m\n")
    _run(spec, "hermes")
    assert yaml.safe_load(path.read_text())["mcp_servers"]["surf"]["command"] == "uvx"


def test_codex_without_cli_appends_valid_toml(home, spec):
    path = home / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text('model = "gpt-5"\n')
    assert _run(spec, "codex")["Codex CLI"].status == "installed"
    data = tomllib.loads(path.read_text())
    assert data["model"] == "gpt-5"
    assert data["mcp_servers"]["surf"] == {"command": "uvx", "args": spec.args, "env": {"K": "v"}}
    assert _run(spec, "codex")["Codex CLI"].status == "exists"


def test_uninstall_json(home, spec):
    _run(spec, "cursor")
    clients, explicit = ai.select_clients("cursor")
    [result] = ai.uninstall(spec, clients, explicit=explicit)
    assert result.status == "removed"
    assert "surf" not in json.loads(ai.Cursor().path().read_text())["mcpServers"]


def test_select_clients_validation():
    assert len(ai.select_clients("all")[0]) == len(ai.CLIENTS)
    with pytest.raises(ValueError, match="unknown client"):
        ai.select_clients("cursor,nope")


def test_claude_code_cli_argument_order(monkeypatch, spec):
    calls = []
    client = ai.ClaudeCode()
    monkeypatch.setattr(client, "_run", lambda args: calls.append(args) or type("P", (), {"returncode": 0})())
    client.add(spec)
    args = calls[0]
    # -e is variadic in the Claude CLI, so the name must precede it.
    assert args[:5] == ["mcp", "add", "-s", "user", "surf"]
    assert args[5:7] == ["-e", "K=v"]
    assert args[7] == "--" and args[8:] == spec.argv
