"""Tests for DocumentExtractService."""
import pytest

from services.document_extract_service import DocumentExtractService


@pytest.fixture
def extractor():
    return DocumentExtractService(max_size_bytes=1024 * 1024, max_text_length=5000)


def test_extract_txt(extractor, tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("Hello, world!\nSecond line.")
    result = extractor.extract_from_path(path)
    assert result.success
    assert "Hello, world!" in result.content
    assert result.format == "text"


def test_extract_html(extractor, tmp_path):
    path = tmp_path / "page.html"
    path.write_text("<html><body><p>Hello <b>world</b></p></body></html>")
    result = extractor.extract_from_path(path)
    assert result.success
    assert "Hello world" in result.content
    assert result.format == "html"


def test_extract_csv(extractor, tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("name,age\nAlice,30\nBob,25")
    result = extractor.extract_from_path(path)
    assert result.success
    assert "Alice | 30" in result.content
    assert result.format == "csv"


def test_extract_json(extractor, tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"name": "Alice", "age": 30}')
    result = extractor.extract_from_path(path)
    assert result.success
    assert '"name": "Alice"' in result.content
    assert result.format == "json"


def test_extract_xml(extractor, tmp_path):
    path = tmp_path / "data.xml"
    path.write_text("<root><item>Hello</item><item>World</item></root>")
    result = extractor.extract_from_path(path)
    assert result.success
    assert "Hello World" in result.content
    assert result.format == "xml"


def test_rejects_zip(extractor, tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    result = extractor.extract_from_path(path)
    assert not result.success
    assert "Rejected" in (result.error or "")


def test_rejects_executable(extractor, tmp_path):
    path = tmp_path / "setup.exe"
    path.write_bytes(b"MZ")
    result = extractor.extract_from_path(path)
    assert not result.success


def test_rejects_oversized(extractor, tmp_path):
    extractor.max_size_bytes = 10
    path = tmp_path / "big.txt"
    path.write_text("x" * 100)
    result = extractor.extract_from_path(path)
    assert not result.success
    assert "exceeds" in (result.error or "").lower()


def test_truncates_long_text(extractor, tmp_path):
    extractor.max_text_length = 10
    path = tmp_path / "long.txt"
    path.write_text("1234567890abcdefghij")
    result = extractor.extract_from_path(path)
    assert result.success
    assert result.truncated
    assert len(result.content) == 10


def test_extract_pdf_requires_pypdf(extractor, tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "sample.pdf"
    # A minimal valid PDF is non-trivial to generate by hand; this test
    # documents the happy path and relies on integration tests for real files.
    result = extractor.extract_from_path(path)
    assert not result.success
    assert "File not found" in (result.error or "")


def test_extract_pdf_reads_real_document(extractor):
    """PdfReader needs a binary stream; a decoded StringIO silently fails."""
    pypdf = pytest.importorskip("pypdf")
    import io

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)

    result = extractor.extract_from_bytes(
        buf.getvalue(), filename="sample.pdf", content_type="application/pdf"
    )
    assert result.success, result.error
    assert result.format == "pdf"


def test_rejects_archive_disguised_by_extension(extractor):
    """The filename is attacker-influenced, so bytes decide."""
    result = extractor.extract_from_bytes(
        b"PK\x03\x04payload-here", filename="report.txt", content_type="text/plain"
    )
    assert not result.success
    assert "zip" in (result.error or "")


def test_rejects_executable_disguised_by_extension(extractor):
    result = extractor.extract_from_bytes(
        b"MZ\x90\x00binary", filename="notes.md", content_type="text/plain"
    )
    assert not result.success
    assert "executable" in (result.error or "")


def test_xml_with_entity_declaration_is_not_parsed(extractor):
    """Billion-laughs / XXE payloads must not reach ElementTree."""
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        b"<root>&lol2;</root>"
    )
    result = extractor.extract_from_bytes(
        payload, filename="bomb.xml", content_type="application/xml"
    )
    # Falls back to tag stripping rather than expanding entities.
    assert result.success
    assert "lol" not in result.content.replace("lol2", "").replace("&lol", "")


def test_plain_xml_still_parses(extractor):
    result = extractor.extract_from_bytes(
        b"<root><item>Hello</item><item>World</item></root>",
        filename="data.xml",
        content_type="application/xml",
    )
    assert result.success
    assert "Hello World" in result.content
