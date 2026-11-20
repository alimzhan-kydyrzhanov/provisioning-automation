# Order-to-Provisioning Automation

A small, runnable model of a SaaS **provisioning automation** pipeline: a **Salesforce** "Closed Won" order
arrives by webhook and the customer's product access is set up automatically — tenant created, **licenses and
entitlements** granted in the product console — with no manual steps. Non-standard deals are routed for
approval, bad orders go to an exception queue, and reverse workflows revoke access when a term ends.

All data is synthetic. The product console is a fake in-memory API; product names are fictional.

## What it does

| Step | Module |
|---|---|
| Receive signed Salesforce webhook (HMAC-SHA256) | `provisioning/webhook.py` |
| Validate the order, report every problem at once | `provisioning/salesforce.py` |
| Standard vs non-standard rules, approval routing (deal desk / provisioning lead) | `provisioning/catalog.py` |
| Create tenant, grant entitlements, retry transient API errors with backoff | `provisioning/workflow.py`, `console.py` |
| Idempotency: the same webhook twice never provisions twice | `workflow.py` |
| Exception queue with the reason (nothing is silently dropped) | `workflow.py`, `store.py` |
| Trial-to-paid conversion, legacy SKU migration | `workflow.py` |
| Term end: revoke access, reclaim licenses, close tenant | `workflow.py` |
| Compliance control: reconcile our entitlements vs the console | `workflow.py` |
| Leadership report: automation coverage, time saved, error rate, SLA | `provisioning/reports.py` |
| Audit log of every action | `store.py` |

## Run

```bash
python -m provisioning            # full lifecycle demo + report
python -m pytest -q               # 23 tests
python -m provisioning --serve    # webhook on :8080

docker build -t provisioning . && docker run --rm provisioning
```

Send a signed webhook to the running server:

```bash
BODY=$(python -c "import json;print(json.dumps(json.load(open('data/sample_orders.json'))[0]))")
SIG=$(python -c "import sys,hmac,hashlib;print(hmac.new(b'dev-secret',sys.argv[1].encode(),hashlib.sha256).hexdigest())" "$BODY")
curl -s -X POST localhost:8080/webhooks/salesforce -H "X-Signature: $SIG" -d "$BODY"
```

Python 3.10+, standard library only (pytest for tests). Operational procedures: see `RUNBOOK.md`.
