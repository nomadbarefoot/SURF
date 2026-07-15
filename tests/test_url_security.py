from utils.url_security import safe_url_for_log


def test_log_url_removes_credentials_path_query_and_fragment():
    assert (
        safe_url_for_log("https://user:pass@example.com/private/token?q=secret#fragment")
        == "https://example.com"
    )


def test_log_url_preserves_non_default_port():
    assert safe_url_for_log("http://example.com:8080/path") == "http://example.com:8080"
