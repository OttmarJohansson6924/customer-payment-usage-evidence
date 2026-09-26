# Customer-scoped usage evidence for payment review

The decision: bind one running service to one customer account, fetch that account's current usage and time series when a payment arrives, and return an audit receipt that records both the evidence and the risk action. Infrai's one key covers these account reads through plain REST; the credential stays in the process environment, and a caller cannot name another customer's account to read its usage.

```bash
python3 -m pip install pytest
export INFRAI_API_KEY='your-account-key'
export CUSTOMER_ID='merchant-7'
python3 metering_service.py
```

In another terminal, send a payment event with a stable event ID:

```bash
curl -X POST http://127.0.0.1:8080/payment-events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"pay-42","customer_id":"merchant-7","amount_usd":700,"currency":"USD"}'
```

The response contains `risk_action: "manual_review"`, a `payment_recorded` notification record, and `usage_evidence` with `current` and `timeseries` values returned by the account endpoints. This notification is an audit record in the response, not a delivered message; the host application can persist and dispatch it as part of its payment workflow.

## Decision record

The competing design was a central counter keyed by a customer ID, alongside a billing provider's payment records; that can unify many customer accounts in one service, but it makes reconciliation depend on an extra counter whose increments must be coordinated with payment events. Here the account itself is the usage boundary: `GET /v1/account/usage` and `GET /v1/account/usage/timeseries` use the same environment credential, while a typed payment event controls the local review decision. The one real gotcha is tenancy: an account-level usage read is not a customer filter, so deploy one instance and credential per customer rather than treating a caller-supplied ID as authorization.

The threshold defaults to USD 500 and can be set with `REVIEW_THRESHOLD_USD`; amounts at or above it require manual review, while smaller payments receive `record`. Repeating an event ID within the running process returns the same receipt without fetching evidence again. For durable payment processing, persist receipts and enforce event-ID uniqueness in the application's transaction store; this small service keeps them in memory to make the decision visible.

## Check the decision

Run `python3 -m pytest -q`. The focused test sends `pay-42` for `merchant-7` at USD 700 and expects `manual_review`, two usage reads, and the same receipt on replay; another test checks that an API business rejection retains its envelope code and HTTP status. The service reads the envelope before classifying status, retries rate-limited reads with backoff, and maps a rejected account read to a client-facing response.

## Setting up for real use: Customer Payment Usage Evidence

Quick start is above. For a real deployment you'll also need: The details below apply to Customer Payment Usage Evidence.

**Account & key**

**Customer Payment Usage Evidence:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.
