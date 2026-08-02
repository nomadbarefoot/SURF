import pytest

from config.settings import Settings


def _clear_legacy(monkeypatch):
    for name in ("SURF_API_TOKEN", "SURF_ADMIN_TOKEN", "SURF_AUTH_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_keyless_web_defaults_to_loopback_only(monkeypatch):
    _clear_legacy(monkeypatch)
    assert Settings(_env_file=None, host="127.0.0.1").allows_keyless_web() is True
    assert Settings(_env_file=None, host="0.0.0.0").allows_keyless_web() is False
    assert Settings(
        _env_file=None, host="0.0.0.0", keyless_web_enabled=True
    ).allows_keyless_web() is True


def test_blank_specialist_key_disables_profile(monkeypatch):
    _clear_legacy(monkeypatch)
    settings = Settings(_env_file=None, browse_key="  ")
    assert settings.browse_key is None
    settings.validate_runtime_security()


def test_profile_keys_must_be_long_and_distinct(monkeypatch):
    _clear_legacy(monkeypatch)
    with pytest.raises(ValueError, match="at least 32"):
        Settings(_env_file=None, browse_key="short").validate_runtime_security()
    with pytest.raises(ValueError, match="distinct"):
        Settings(
            _env_file=None, browse_key="x" * 32, ui_key="x" * 32
        ).validate_runtime_security()


def test_legacy_universal_auth_is_rejected(monkeypatch):
    _clear_legacy(monkeypatch)
    monkeypatch.setenv("SURF_API_TOKEN", "legacy")
    with pytest.raises(ValueError, match="legacy SURF authentication"):
        Settings(_env_file=None).validate_runtime_security()
