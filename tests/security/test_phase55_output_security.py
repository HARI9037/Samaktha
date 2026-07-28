"""Phase 5.5 tests — Output Security Filter.

Validates:
- API key redaction
- Password masking
- Safe output preservation
"""
from app.security.output_filter import OutputSecurityFilter
from app.security.security_metrics import SecurityMetricsCollector


def test_output_filter_safe_output():
    filter_ = OutputSecurityFilter()
    safe_text = "The weather is sunny today."
    assert filter_.filter_text(safe_text) == safe_text


def test_output_filter_redacts_api_key():
    metrics = SecurityMetricsCollector()
    filter_ = OutputSecurityFilter(metrics=metrics)
    
    text = "Connecting with api_key='sk_live_12345'..."
    filtered = filter_.filter_text(text)
    
    assert "sk_live_12345" not in filtered
    assert "[REDACTED]" in filtered
    assert metrics.get_snapshot()["secret_redactions"] == 1


def test_output_filter_redacts_dict():
    filter_ = OutputSecurityFilter()
    data = {
        "status": "success",
        "data": {
            "user": "admin",
            "password": "supersecretpassword123",
            "details": ["token=abc", "safe"]
        }
    }
    
    filtered = filter_.filter_dict(data)
    
    assert filtered["status"] == "success"
    assert "supersecretpassword123" not in filtered["data"]["password"]
    assert "[REDACTED]" in filtered["data"]["password"]
    
    assert "token" in filtered["data"]["details"][0]
    assert "[REDACTED]" in filtered["data"]["details"][0]
    assert "abc" not in filtered["data"]["details"][0]
    assert filtered["data"]["details"][1] == "safe"
