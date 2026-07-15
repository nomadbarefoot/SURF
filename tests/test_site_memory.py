"""Site-memory privacy and persistence behavior."""
from utils.site_memory import SiteMemory, SiteMemoryManager


def test_access_stats_create_origin_scoped_record(tmp_path):
    manager = SiteMemoryManager(db_path=tmp_path / "memory.db")

    assert manager.update_access_stats(
        "https://Example.com/private/path?token=secret", success=True
    )
    memory = manager.get_site_memory("https://example.com/another?secret=two")

    assert memory is not None
    assert memory.site_url == "https://example.com"
    assert memory.access_count == 1
    assert memory.success_rate == 0.1


def test_plaintext_session_and_cookie_values_are_never_persisted(tmp_path):
    manager = SiteMemoryManager(db_path=tmp_path / "memory.db")
    manager.save_site_memory(
        SiteMemory(
            site_url="https://example.com/path?token=secret",
            session_data={"authorization": "secret"},
            cookies=[{"name": "session", "value": "secret"}],
            last_accessed=1,
            access_count=1,
            success_rate=1.0,
            custom_data={},
        )
    )

    memory = manager.get_site_memory("https://example.com")
    assert memory is not None
    assert memory.session_data == {}
    assert memory.cookies == []
