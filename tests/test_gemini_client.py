from app.utils.gemini_helper import create_gemini_client


def test_gemini_client_requests_v1beta(monkeypatch):
    monkeypatch.setattr("app.utils.gemini_helper.GEMINI_API_KEY", "test-key")
    client = create_gemini_client()
    assert client._api_client._http_options.api_version == "v1beta"
