# Runbook: Provisioning Automation

## Order statuses
`RECEIVED` → `PROVISIONED` (standard, automatic)
`RECEIVED` → `PENDING_APPROVAL` → `PROVISIONED` / `REJECTED`
`RECEIVED` → `EXCEPTION` (validation failed or console unavailable after 3 retries)

## Daily checks
1. Exception queue: `SELECT * FROM exceptions ORDER BY created_at;`
2. Pending approvals older than 4 h (SLA risk): `SELECT * FROM approvals WHERE status='PENDING';`
3. Reconciliation drift (`engine.reconcile()`) must be empty. Any drift = someone changed the console by hand
   or a call half-failed. Do not "fix" the console silently: find the order in `audit_log` first.

## Exception: validation error
Cause: bad data in Salesforce (missing admin email, unknown SKU, wrong date).
Fix: ask Sales Ops to correct the Opportunity and re-send the webhook. The order id is the same, and
`EXCEPTION` orders are allowed to be re-processed, so no duplicate is created.

## Exception: console error after 3 retries
Cause: product console outage. Check its status page. When it is back, re-send the webhook.
Partly granted licenses are safe: grants are idempotent (same seats → same result).

## Non-standard request
Routed to `deal_desk` (discount > 30%, unusual term) or `provisioning_lead` (> 5000 seats).
Approve: `engine.approve(order_id, approver)`; reject: `engine.reject(order_id, approver, reason)`.

## Term end (nightly job)
`engine.deprovision_expired(today)` revokes expired entitlements, reclaims seats and closes tenants
with nothing left. Every action is in `audit_log`.

## Month / quarter end
Expect order spikes. Watch the exception queue every hour and keep approvers on call.
