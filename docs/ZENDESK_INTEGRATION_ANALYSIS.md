# Zendesk Integration Analysis — Edge Box Provisioning

**Date**: 2026-02-18
**Context**: Hardware Asset Tracker edge box provisioning workflow
**Existing Foundation**: Zendesk API client (`app/zendesk.py`), admin page (`/admin/zendesk`)

---

## Current Capabilities

**Already Built:**
- ✅ Async Zendesk API client (httpx-based)
- ✅ Rate limit handling with exponential backoff
- ✅ Organizations, tickets, users, ticket fields endpoints
- ✅ Admin page for testing connection and browsing data
- ✅ Configuration via `.env` (ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN)

**What's Missing:**
- ❌ Credentials on NUC (needs user to provide)
- ❌ Write operations (create/update tickets)
- ❌ Custom field extraction/mapping
- ❌ Integration with provisioning workflow

---

## Option 1: Ticket → Provisioning Workflow

### Concept
A Zendesk support ticket (e.g., "Deploy edge box for Acme Corp pilot") triggers or pre-populates a provisioning record in the asset tracker.

### Technical Implementation

**Approach A: Manual Link**
1. Support team creates Zendesk ticket for deployment
2. In asset tracker provisioning modal, add "Zendesk Ticket ID" field
3. On provisioning create, fetch ticket data via API:
   ```python
   ticket = await client.get_ticket(ticket_id)
   org = await client.get_organization(ticket.organization_id)
   # Pre-populate: customer name, site (if in custom field), deployment type
   ```
4. Display ticket info in provisioning record (subject, requester, org)

**Approach B: Zendesk Trigger/Webhook (Advanced)**
1. Configure Zendesk trigger: "When ticket tagged 'edge-box-deployment' → webhook"
2. Asset tracker receives webhook → creates draft provisioning record
3. Sales/ops reviews draft and confirms

### What's Possible
✅ **Fetch ticket data** — organizations, requester, subject, custom fields
✅ **Pre-populate fields** — customer name, deployment type (if in ticket)
✅ **Link provisioning to ticket** — store ticket_id, show ticket context
✅ **Validate against Zendesk** — ensure customer org exists in Zendesk

### What's Not Possible
❌ **Auto-create sites** — Zendesk doesn't have physical site/location data structured for hardware
❌ **Inventory allocation** — Zendesk doesn't know which edge box serial to assign
❌ **Full automation** — Still needs human judgment (which box, priority, timeline)

### Should We Do This?

**✅ YES, if:**
- Support team uses Zendesk as the **entry point** for all deployments
- Tickets contain structured data (custom fields for deployment type, customer, timeline)
- You want to reduce manual re-entry of customer names

**❌ NO, if:**
- Deployment requests come from other sources (email, Slack, sales team directly)
- Zendesk tickets are too unstructured (just free-text descriptions)
- The overhead of managing Zendesk ticket IDs doesn't match workflow

**Recommendation**: **Start small with Approach A** (manual ticket ID entry). Add a "Zendesk Ticket" field to provisioning, fetch and display ticket context. See if the team actually uses it before building more automation.

---

## Option 2: Field Standardization

### Concept
Use Zendesk as the **source of truth** for customer names, organizations, and deployment metadata to ensure consistency across systems.

### Technical Implementation

1. **Customer Dropdown from Zendesk Orgs**
   ```python
   orgs = await client.list_organizations()
   # Populate "Customer" dropdown in provisioning modal
   # Ensures spelling consistency (no "Acme Corp" vs "ACME Corporation")
   ```

2. **Deployment Type from Ticket Fields**
   ```python
   fields = await client.list_ticket_fields()
   # Find custom field "deployment_type" (pilot/customer/demo/etc)
   # Use same values in asset tracker for consistency
   ```

3. **Sync on Create**
   - When creating provisioning, validate customer name exists in Zendesk
   - If not found, prompt to create Zendesk org first

### What's Possible
✅ **Customer name standardization** — pull from Zendesk orgs (exact spelling)
✅ **Field value alignment** — use same picklist values as Zendesk custom fields
✅ **Two-way validation** — ensure asset tracker data matches Zendesk records

### What's Not Possible
❌ **Physical site/location data** — Zendesk orgs have address fields, but not structured "sites" like your Sites table
❌ **Hardware-specific fields** — Serial numbers, part numbers, inventory status not in Zendesk
❌ **Real-time sync** — Changes in Zendesk won't auto-update asset tracker (unless polling/webhooks)

### Should We Do This?

**✅ YES, if:**
- You frequently have data inconsistencies (customer name typos, different spellings)
- Zendesk is the **authoritative system** for customer records
- You want Sales/Support to manage customer data, not asset tracker users

**❌ NO, if:**
- Your customer list is small and stable (rarely changes)
- Asset tracker already has good customer data entry practices
- Zendesk orgs don't map 1:1 to your customers (e.g., Zendesk has end-users, you track integrators)

**Recommendation**: **Maybe, but low priority**. This is more useful for larger orgs with messy customer data. For a small team, the added complexity isn't worth it unless you're already having data quality issues.

---

## Option 3: Notification Workflow

### Concept
When edge box provisioning stages change (Staged → Configured → Registered → ...), update the linked Zendesk ticket and notify stakeholders.

### Technical Implementation

1. **Link Provisioning to Ticket**
   - Add `zendesk_ticket_id` field to `device_provisioning` table
   - When creating provisioning, optionally link to ticket

2. **Stage Change → Ticket Comment**
   ```python
   # When provisioning advances (e.g., Configured → Registered):
   if provisioning.zendesk_ticket_id:
       await client.add_ticket_comment(
           ticket_id=provisioning.zendesk_ticket_id,
           comment=f"Edge box {serial} advanced to {stage} by {user.name}"
       )
   ```

3. **Completion → Close Ticket**
   - When all 7 stages complete, optionally mark Zendesk ticket as "Solved"

4. **Watchers via Zendesk**
   - Zendesk ticket followers auto-notified when comments added
   - Stakeholders (sales, support, customer) get email updates

### What's Possible
✅ **Auto-comment on stage changes** — Zendesk API supports adding comments
✅ **Ticket status updates** — Mark ticket "In Progress" / "Solved" based on provisioning state
✅ **Stakeholder notifications** — Zendesk handles email/Slack notifications to ticket followers
✅ **Audit trail** — Ticket becomes full history of edge box deployment

### What's Not Possible
❌ **Bidirectional sync** — Zendesk ticket changes won't auto-update provisioning (would need webhooks + complex logic)
❌ **Fine-grained control** — Zendesk notifications are all-or-nothing for ticket followers
❌ **Non-Zendesk users** — Internal team members not in Zendesk miss notifications (unless you dual-post to Slack/email)

### Should We Do This?

**✅ YES, if:**
- Customers or sales team actively monitor Zendesk tickets
- You want a **single thread** for deployment status (no scattered Slack/email updates)
- Support team needs visibility into hardware provisioning progress
- You're already linking tickets to deployments (Option 1)

**❌ NO, if:**
- Zendesk is rarely checked by the people who care about provisioning
- You'd rather use Slack or email for notifications (simpler, no Zendesk dependency)
- Most stakeholders are internal and don't have Zendesk access

**Recommendation**: **YES, but only after Option 1 is working**. This builds on ticket linking — once you're storing `zendesk_ticket_id` in provisioning, adding stage-change comments is straightforward. It's a natural evolution.

---

## Recommended Implementation Sequence

### Phase 1: Foundation (Do This First)
1. **Add Zendesk credentials to NUC** — user provides subdomain/email/token
2. **Test admin page** — verify connection, browse orgs/tickets/fields
3. **Understand your ticket structure** — what custom fields exist? How are deployments tracked?

### Phase 2: Ticket Linking (Option 1 — Manual)
1. **Add `zendesk_ticket_id` to provisioning** (Migration 006)
2. **Add ticket ID field to create modal**
3. **Fetch and display ticket context** — show ticket subject, requester, org in provisioning record
4. **Validate**: Does the team actually use this? Do tickets have useful data?

### Phase 3: Notification Workflow (Option 3)
*Only if Phase 2 proves valuable*
1. **Add ticket comments on stage changes**
2. **Mark ticket "Solved" on provisioning completion**
3. **Monitor**: Do stakeholders find the updates useful?

### Phase 4: Field Standardization (Option 2)
*Only if data quality is a problem*
1. **Customer dropdown from Zendesk orgs** (optional enhancement)
2. **Deployment type alignment** (if Zendesk has custom field)

---

## What NOT to Build

❌ **Full Zendesk ↔ Asset Tracker sync** — Too complex, maintenance burden
❌ **Zendesk as hardware inventory system** — Wrong tool, use asset tracker for that
❌ **Webhook-based auto-provisioning** — Requires Zendesk admin setup, brittle, hard to debug
❌ **Sites table from Zendesk orgs** — Zendesk org ≠ physical site/location

---

## Key Questions to Answer Before Building

1. **Do deployment requests start in Zendesk?**
   - If YES → Option 1 makes sense
   - If NO (email, Slack, verbal) → Option 1 adds overhead

2. **Do customers/sales check Zendesk tickets for status?**
   - If YES → Option 3 (notifications) is valuable
   - If NO → Just use asset tracker, no need to update Zendesk

3. **Is customer data messy (typos, inconsistent names)?**
   - If YES → Option 2 (standardization) helps
   - If NO → Not worth the complexity

4. **What's in your Zendesk ticket custom fields?**
   - Deployment type? Customer name? Timeline? Edge box serial?
   - If rich structured data → integration easier
   - If just free-text → harder to extract value

---

## Cost/Benefit Summary

| Option | Effort | Value if Zendesk is Central | Value if Zendesk is Peripheral |
|--------|--------|------------------------------|--------------------------------|
| **1. Ticket → Provisioning** | Medium | High (reduces re-entry) | Low (adds overhead) |
| **2. Field Standardization** | Medium | Medium (data quality++) | Low (unnecessary complexity) |
| **3. Notification Workflow** | Low (builds on #1) | High (stakeholder visibility) | Low (no one checks Zendesk) |

---

## Final Recommendation

**Start with Phase 1 (credentials + exploration), then decide:**

1. **If Zendesk is your deployment hub** → Build Option 1 (ticket linking) + Option 3 (notifications)
2. **If Zendesk is just support tickets** → Skip all integrations, keep asset tracker standalone
3. **If unsure** → Add credentials, explore your tickets, see if there's structured data worth pulling

**Don't build it just because you can** — build it because it solves a real workflow pain point (manual re-entry, scattered notifications, data inconsistency). If those problems don't exist, Zendesk integration adds complexity without value.

---

**Next Steps**: Review your Zendesk instance, check ticket structure, decide if Options 1/3 would reduce friction. I can implement any of these once you provide credentials and confirm the use case.
