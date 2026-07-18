import argparse
import json

import pytest

import cli.surf_cli as surf_cli


@pytest.fixture(autouse=True)
def configured_surf_url(monkeypatch):
    monkeypatch.setenv("SURF_URL", "127.0.0.1:17777")


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_fetch_unwraps_server_data_envelope(monkeypatch, capsys):
    monkeypatch.setattr(
        surf_cli,
        "_post",
        lambda *_args, **_kwargs: {
            "success": True,
            "data": {"status": 200, "text": "hello from SURF"},
        },
    )
    args = argparse.Namespace(
        url="https://example.com", timeout=3.0, json=False
    )

    surf_cli.cmd_fetch(args)

    assert capsys.readouterr().out.strip() == "hello from SURF"


def test_fetch_json_prints_raw_response(monkeypatch, capsys):
    response = {"success": True, "data": {"status": 200, "json": {"ok": 1}}}
    monkeypatch.setattr(surf_cli, "_post", lambda *_args, **_kwargs: response)
    args = argparse.Namespace(url="https://example.com", timeout=3.0, json=True)

    surf_cli.cmd_fetch(args)

    assert json.loads(capsys.readouterr().out) == response


def test_extract_partial_failure_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        surf_cli,
        "_post",
        lambda *_args, **_kwargs: {
            "success": True,
            "partial": True,
            "results": [
                {"url": "https://good.example", "content": "content"},
                {"url": "https://bad.example", "error": "blocked"},
            ],
        },
    )
    args = argparse.Namespace(
        urls=["https://good.example", "https://bad.example"],
        timeout=3.0,
        json=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        surf_cli.cmd_extract(args)

    assert exc_info.value.code == 1
    assert "content" in capsys.readouterr().out


def test_parser_supports_timeout_json_and_preflight():
    parser = surf_cli._build_parser()

    args = parser.parse_args(["search", "query", "--timeout", "4", "--json"])
    assert args.timeout == 4
    assert args.json is True

    args = parser.parse_args(["preflight", "--probe-url", "https://example.com"])
    assert args.command == "preflight"
    assert args.probe_url == "https://example.com"


def test_preflight_reports_http_failures(monkeypatch, capsys):
    monkeypatch.setattr(
        surf_cli,
        "_request",
        lambda *_args, **_kwargs: FakeResponse({"success": False}, status_code=503),
    )
    args = argparse.Namespace(
        probe_url="https://example.com", timeout=3.0, json=False
    )

    with pytest.raises(SystemExit) as exc_info:
        surf_cli.cmd_preflight(args)

    assert exc_info.value.code == 1
    assert "fail" in capsys.readouterr().out
