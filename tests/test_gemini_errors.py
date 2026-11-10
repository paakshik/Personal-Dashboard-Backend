import pytest
from app.utils.gemini_helper import describe_gemini_error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (Exception("API key invalid"), "Check GEMINI_API_KEY"),
        (Exception("RESOURCE_EXHAUSTED quota"), "quota or rate limit"),
        (Exception("model not_found"), "model or API resource was not found"),
    ],
)
def test_gemini_errors_are_actionable_without_secrets(error, expected):
    assert expected in describe_gemini_error(error)
