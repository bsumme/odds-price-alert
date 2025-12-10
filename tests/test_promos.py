from datetime import date

from services import promos


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_get_promotions_falls_back_when_live_blocked(monkeypatch):
    def fake_get(*_, **__):
        raise promos.RequestException("blocked")

    monkeypatch.setattr(promos.requests, "get", fake_get)

    result = promos.get_promotions(today=date(2024, 9, 2))  # Monday -> football day fallback

    assert result["used_fallback"] is True
    assert any(promo.get("source") == "schedule" for promo in result["promos"])


def test_fetch_live_promos_extracts_generic_fields(monkeypatch):
    payload = {
        "cards": [
            {
                "title": "Sample Boost",
                "description": "Test promotion for parsing",
                "link": "https://example.com/promo",
            }
        ]
    }

    def fake_get(*_, **__):
        return DummyResponse(payload)

    monkeypatch.setattr(promos.requests, "get", fake_get)

    result = promos.fetch_live_promos()

    assert not result["errors"]
    assert any(promo["title"] == "Sample Boost" for promo in result["promos"])
