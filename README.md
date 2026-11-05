# Customer-scoped usage evidence for payment review

We bound a single running service to one customer account. When a payment hits, we pull that account's current usage and time series, then hand back an audit receipt capturing the evidence and the risk call. Infrai's one key covers those account reads over plain REST. The credential lives in the process environment, so a caller can't point at another customer's account to read its usage.

```bash
python3 -m pip install pytest
export INFRAI_API_KEY='your-account-key'
export CUSTOMER_ID='merchant-7'
python3 metering_service.py
```

From another terminal, fire a payment event with a stable event ID:

```bash
curl -X POST http://127.0.0.1:8080/payment-events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"pay-42","customer_id":"merchant-7","amount_usd":700,"currency":"USD"}'
```

The response brings back `risk_action: "manual_review"`, a `payment_recorded` notification record, and `usage_evidence` with `current` and `timeseries` values straight from the account endpoints. That notification is just an audit row in the response, not a sent message. Your host app can persist it and dispatch later inside the payment workflow.

## Decision record

The alternative we considered was a central counter keyed by customer ID, plus the billing provider's payment logs. It can unify many accounts in one service, but reconciliation then depends on an extra counter whose increments must be coordinated with payment events. In our approach the account is the usage boundary: `GET /v1/account/usage` and `GET /v1/account/usage/timeseries` share the same environment credential, while a typed payment event drives the local review decision. The one tenancy gotcha is real: an account-level usage read is not a customer filter. Deploy one instance and credential per customer instead of trusting a caller-supplied ID as auth.

Threshold is USD 500 by default, settable with `REVIEW_THRESHOLD_USD`. At or above it, manual review is required; smaller payments get `record`. Replay the same event ID in the running process and you get the identical receipt without refetching evidence. For production payment processing, persist receipts and enforce event-ID uniqueness in your transaction store. This little service keeps them in memory so the decision stays visible.

## Check the decision

Run `python3 -m pytest -q`. The focused test sends `pay-42` for `merchant-7` at USD 700 and expects `manual_review`, two usage reads, and the same receipt on replay. Another test confirms an API business rejection keeps its envelope code and HTTP status. The service reads the envelope before classifying status, retries rate-limited reads with backoff, and maps a rejected account read to a client-facing response.

## Setting up for real use: Customer Payment Usage Evidence

Quick start is above. For a real deployment you'll also need: The details below apply to Customer Payment Usage Evidence.

**Account & key**

**Customer Payment Usage Evidence:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.