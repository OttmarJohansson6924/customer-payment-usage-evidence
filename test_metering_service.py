import io
import json
from urllib.error import HTTPError

import pytest

from metering_service import InfraiError, Meter, PaymentEvent, account_read


def test_large_payment_requires_review_and_duplicate_reuses_evidence():
    calls = []

    def read(path, key):
        calls.append((path, key))
        return {"snapshot": len(calls)}

    meter = Meter("merchant-7", "test-key", 500, read)
    event = PaymentEvent.parse({"event_id": "pay-42", "customer_id": "merchant-7",
                                "amount_usd": 700, "currency": "USD"})
    receipt = meter.record(event)
    assert receipt["risk_action"] == "manual_review"
    assert receipt["notification"]["event_id"] == "pay-42"
    assert receipt["usage_evidence"]["timeseries"] == {"snapshot": 2}
    assert meter.record(event) is receipt
    assert len(calls) == 2


def test_business_rejection_is_decoded_before_http_error():
    def opener(request, timeout):
        payload = json.dumps({"ok": False, "error": {"code": "INVALID_ARGUMENT"},
                              "data": None, "metadata": {}}).encode()
        raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(payload))

    with pytest.raises(InfraiError) as caught:
        account_read("/v1/account/usage", "test-key", opener=opener)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert caught.value.status == 400
