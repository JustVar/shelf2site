# Salesforce Integration — Questions for Rowan

**From:** Justin / Hardware & QA Team
**Date:** 02/25/2026
**Purpose:** Get what we need to build the Salesforce integration correctly from day one

---

## Background

The Hardware Asset Tracker already tracks edge box provisioning, customer orders (AT-XXXX),
and device inventory. We want to connect it to Salesforce so the two systems stay in sync
without manual data entry in both places.

We plan to use **OAuth 2.0 Client Credentials flow** (server-to-server, no user login required)
so the NUC server can talk to Salesforce directly and securely. This avoids hardcoding any
user's credentials and is the right pattern for background sync jobs.

---

## What We Need from Rowan

### 1. Connected App Setup (Salesforce Admin Task)

Please create a **Connected App** in Salesforce with the following settings:

- **OAuth Flows enabled:** Client Credentials (OAuth 2.0)
- **Scopes required:** `api`, `refresh_token` (or `full` if easier)
- **IP relaxation:** Relax IP restrictions (the NUC's IP may change if the lab network changes)

Once created, please share:

| Item | Example |
|---|---|
| Consumer Key (Client ID) | `3MVG9...` |
| Consumer Secret (Client Secret) | (send securely — we'll put it in `.env` on the NUC) |
| Salesforce instance URL | `https://example.my.salesforce.com` |
| API version to target | e.g. `v59.0` |

---

### 2. Data Direction — What Goes Which Way?

We need to agree on what flows in each direction before writing any sync code.

**Our current thinking (please confirm or correct):**

| Data | Direction | Notes |
|---|---|---|
| Customer order status (new→shipped→installed) | Asset Tracker → Salesforce | We own the fulfillment pipeline; SF should see current status |
| Opportunity / Order ID linkage | Salesforce → Asset Tracker | We already store `salesforce_opp_id` and `salesforce_order_id` on each order; SF is the source |
| "Received" status on edge boxes | Salesforce → Asset Tracker | Does SF track when a customer receives hardware? |
| PO / vendor stock data | Salesforce → Asset Tracker | Is SF already tracking OEM purchase orders and stock levels? |
| Device serial numbers at a customer site | Asset Tracker → Salesforce | Should we push provisioned serial numbers back to SF asset records? |

**What we are NOT trying to do:**
- Replace any Salesforce workflows or screens that Sales/SEs already use
- Mirror all of Salesforce into the asset tracker
- Give the asset tracker write access to Opportunities or Accounts

---

### 3. Salesforce Object Mapping

We need to know which SF objects correspond to what we're already tracking.

| Asset Tracker Field | Which Salesforce Object / Field? |
|---|---|
| `salesforce_opp_id` (on Customer Orders) | Opportunity.Id? |
| `salesforce_order_id` (on Customer Orders) | Order.Id? Order Number? |
| Customer name / company | Account.Name? |
| "Received" status | Custom field on Opportunity? Order? |
| Edge box serial number at a site | Asset.SerialNumber? Custom object? |
| PO / vendor order | Custom object? Standard Order Products? |

If Salesforce uses custom objects for any of these, please share the API name
(e.g. `Hardware_Order__c`) so we can reference them correctly.

---

### 4. Sync Frequency

We're planning:
- **Nightly pull** from Salesforce (new orders, status updates, received confirmations)
- **On-event push** to Salesforce when a customer order status changes in the asset tracker

Does that cadence work, or do you need near-real-time updates on specific events?

---

### 5. Sandbox / Testing Environment

- Do you have a Salesforce **sandbox** we can test against first before touching production data?
- If yes, please provide a separate Connected App (or same app pointed at sandbox URL) for our dev/test runs

---

## What We'll Build Once We Have This

1. A Salesforce API client in the asset tracker (`app/integrations/salesforce.py`) using Client Credentials — no user password stored
2. Admin page at `/admin/salesforce` showing connection status, last sync time, and a manual sync button
3. Nightly background sync (same pattern as our existing nightly jobs)
4. Customer Orders page will auto-populate details when a Salesforce Opp ID is entered

The admin page will be ready and waiting as soon as we have the Connected App credentials.

---

## No Action Needed From Sales Team

Sales and SEs keep working in Salesforce exactly as they do today.
The integration runs silently in the background — the asset tracker reads/writes
specific fields only, and does not change how Salesforce looks or behaves for anyone.

---

*Questions? Reach out to Justin directly.*
