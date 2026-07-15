"""Finance selector extraction regressions."""
from services.finance_service import _extract_field


def test_single_capture_is_unchanged():
    value = _extract_field(
        '"mean":"1,234.50"',
        {"type": "regex", "pattern": r'"mean":"([\d,.]+)"'},
    )

    assert value == "1,234.50"


def test_multi_capture_record_preserves_all_fields():
    value = _extract_field(
        '"acqMode":"Market","acqName":"Buyer","acqfromDt":"2026-07-01"',
        {
            "type": "regex",
            "pattern": r'"acqMode":"([^"]+)","acqName":"([^"]+)","acqfromDt":"([^"]+)"',
        },
    )

    assert value == "Market | Buyer | 2026-07-01"
