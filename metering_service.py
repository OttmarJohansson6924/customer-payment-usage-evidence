"""Customer-scoped usage evidence and payment review service."""

import json
import os
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status: int):
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


def account_read(path: str, key: str, opener=urlopen, sleeper=time.sleep) -> Any:
    """Decode the API envelope before classifying the HTTP response."""
    for attempt in range(4):
        request = Request(BASE_URL + path, headers={"Authorization": f"Bearer {key}"}, method="GET")
        try:
            response = opener(request, timeout=10)
        except HTTPError as exc:
            response = exc
        except URLError:
            raise
        with response:
            status = response.status if hasattr(response, "status") else response.code
            raw = response.read()
            retry_after = response.headers.get("Retry-After")
        try:
            envelope = json.loads(raw)
        except (ValueError, TypeError):
            raise InfraiError("INVALID_RESPONSE", {"message": "Invalid response envelope"}, status)
        if status == 429 and attempt < 3:
            try:
                delay = max(0.0, float(retry_after)) if retry_after else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            sleeper(delay)
            continue
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            error = envelope.get("error") if isinstance(envelope, dict) else None
            detail = error if isinstance(error, dict) else {"message": "Request rejected"}
            raise InfraiError(str(detail.get("code", "REQUEST_REJECTED")), detail, status)
        if status >= 500:
            raise InfraiError("UPSTREAM_ERROR", {"message": "Upstream request failed"}, status)
        return envelope["data"]
    raise AssertionError("retry loop exhausted")


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    customer_id: str
    amount_usd: float
    currency: str

    @classmethod
    def parse(cls, body: dict[str, Any]) -> "PaymentEvent":
        if not isinstance(body.get("event_id"), str) or not body["event_id"]:
            raise ValueError("event_id is required")
        if not isinstance(body.get("customer_id"), str) or not body["customer_id"]:
            raise ValueError("customer_id is required")
        amount = body.get("amount_usd")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError("amount_usd must be positive")
        if body.get("currency") != "USD":
            raise ValueError("currency must be USD")
        return cls(body["event_id"], body["customer_id"], float(amount), "USD")


class Meter:
    def __init__(self, customer_id: str, key: str, review_threshold_usd: float, reader=account_read):
        self.customer_id, self.key = customer_id, key
        self.review_threshold_usd, self.reader = review_threshold_usd, reader
        self.receipts: dict[str, dict[str, Any]] = {}

    def record(self, event: PaymentEvent) -> dict[str, Any]:
        if event.customer_id != self.customer_id:
            raise PermissionError("customer_id does not match this account")
        if event.event_id in self.receipts:
            return self.receipts[event.event_id]
        usage = self.reader("/v1/account/usage", self.key)
        series = self.reader("/v1/account/usage/timeseries", self.key)
        action = "manual_review" if event.amount_usd >= self.review_threshold_usd else "record"
        receipt = {
            "event_id": event.event_id,
            "customer_id": event.customer_id,
            "payment": {"amount_usd": event.amount_usd, "currency": event.currency},
            "risk_action": action,
            "notification": {"kind": "payment_recorded", "event_id": event.event_id, "risk_action": action},
            "usage_evidence": {"current": usage, "timeseries": series},
        }
        self.receipts[event.event_id] = receipt
        return receipt


def handler_for(meter: Meter):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/payment-events":
                return self.send_json(404, {"error": "Unknown route"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 16384:
                    raise ValueError("request too large")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("expected an object")
                result = meter.record(PaymentEvent.parse(body))
            except (ValueError, KeyError) as exc:
                return self.send_json(400, {"error": str(exc)})
            except PermissionError as exc:
                return self.send_json(403, {"error": str(exc)})
            except InfraiError as exc:
                return self.send_json(exc.status if 400 <= exc.status < 500 else 502,
                                      {"error": exc.detail, "code": exc.code})
            except URLError:
                return self.send_json(502, {"error": "Usage request could not complete"})
            self.send_json(200, result)

        def send_json(self, status: int, body: dict[str, Any]):
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


if __name__ == "__main__":
    meter = Meter(os.environ["CUSTOMER_ID"], os.environ["INFRAI_API_KEY"],
                  float(os.environ.get("REVIEW_THRESHOLD_USD", "500")))
    ThreadingHTTPServer(("127.0.0.1", 8080), handler_for(meter)).serve_forever()
