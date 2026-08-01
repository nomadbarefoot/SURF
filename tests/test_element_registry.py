import pytest

from services.element_registry import ElementRegistry


def test_registry_is_lru_bounded_per_page_and_session():
    registry = ElementRegistry(per_page=2, per_session=3, ttl=600)
    first = registry.register("s", "p1", 0, "#one", {"tag": "button"})
    second = registry.register("s", "p1", 0, "#two", {"tag": "button"})
    registry.get(first, "s", "p1")  # first is now newer than second
    third = registry.register("s", "p1", 0, "#three", {"tag": "button"})
    with pytest.raises(ValueError):
        registry.get(second, "s", "p1")
    assert registry.get(first, "s", "p1").locator == "#one"
    assert registry.get(third, "s", "p1").locator == "#three"

    registry.register("s", "p2", 0, "#four", {"tag": "button"})
    registry.register("s", "p2", 0, "#five", {"tag": "button"})
    with pytest.raises(ValueError):
        registry.get(first, "s", "p1")


def test_registry_eviction_and_session_scope():
    registry = ElementRegistry()
    handle = registry.register("s1", "p", 0, "button", {"tag": "button"})
    with pytest.raises(ValueError):
        registry.get(handle, "s2", "p")
    registry.evict_page("s1", "p")
    with pytest.raises(ValueError):
        registry.get(handle, "s1", "p")
