"""Guided tour definitions for the Hardware Asset Tracker.

Each tour is a dict with:
  - id: unique string identifier
  - name: display name
  - page_pattern: URL path to match (after ROOT_PATH prefix)
  - description: short description shown in help menu
  - required_access: User property name to check (None = all users)
  - enabled: whether the tour is active (True by default)
  - group: category for grouping in the help menu
  - steps: list of step dicts

Each step has:
  - target: CSS selector for the element to highlight
  - title: step heading
  - description: step body text (supports basic HTML)
  - position: preferred tooltip position ("top", "bottom", "left", "right")
  - highlight_padding: extra px around the target (default 8)
  - wait_for: optional CSS selector to wait for before showing step
  - optional: if True, skip step when target element is missing
"""

import fnmatch
from typing import Optional

TOURS: list[dict] = [
    # ------------------------------------------------------------------
    # Navigating the App (all users, every page)
    # Placed FIRST: page_pattern "*" matches everywhere and checkAndAutoStart
    # picks the first incomplete tour in list order, so a fresh user meets
    # the chrome before any page tour. map_kiosk never sees it (the /api
    # middleware 403s tour fetches for kiosk sessions).
    # ------------------------------------------------------------------
    {
        "id": "nav_tour",
        "name": "Navigating the App",
        "page_pattern": "*",
        "template": "base.html",
        "description": "The sidebar, flyout, theme toggle, and where to find these tours",
        "required_access": None,
        "enabled": True,
        "group": "onboarding",
        "steps": [
            {
                "target": ".sx-nav__header-expanded .sx-nav__toggle-btn",
                "title": "The Navigation Rail",
                "description": (
                    "Collapse the rail to icons with this toggle — everything "
                    "stays one click away."
                ),
                "position": "right",
                # Hidden when the rail is already collapsed (auto-collapse
                # under 1200px or stored preference) and on phones.
                "optional": True,
            },
            {
                "target": '.sx-nav__section[data-section="admin"] .sx-nav__section-header',
                "title": "Grouped Pages",
                "description": (
                    "Sections with sub-pages expand from their header — inline "
                    "when the rail is open, as a flyout when it's collapsed. "
                    "No page jump either way."
                ),
                "position": "right",
                # Admin is the only grouped section and renders only for
                # users with an admin-ish permission.
                "optional": True,
            },
            {
                "target": "#theme-toggle",
                "title": "Light or Dark",
                "description": (
                    "Switch themes any time — every page supports both, and "
                    "your choice sticks across sessions."
                ),
                "position": "right",
                "optional": True,
            },
            {
                "target": "#help-tours-btn",
                "title": "Guided Tours Live Here",
                "description": (
                    "This button opens the tour catalog from any page — "
                    'including a "Tour This Page" shortcut whenever the page '
                    "you're on has one."
                ),
                "position": "right",
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Dashboard (all users)
    # ------------------------------------------------------------------
    {
        "id": "dashboard_tour",
        "name": "Dashboard Overview",
        "description": "A quick orientation to the dashboard overview page.",
        "page_pattern": "/dashboard",
        "enabled": True,
        "required_access": None,
        "group": "onboarding",
        "steps": [
            {
                "title": "What This Page Shows",
                "description": "The dashboard is a read-only overview of the inventory. It surfaces the most useful numbers and recent activity in one place, so you can see at a glance what's deployed, what's pending, and what needs attention.",
                "center": True,
                "optional": True,
            },
            {
                "target": ".db-hero",
                "title": "The Hero Strip",
                "description": "These three tiles are your top-line counts — total items, deployment state, and attention items. They update live as inventory changes.",
                "position": "bottom",
                "optional": True,
            },
            {
                "target": ".db-status-grid",
                "title": "Status by Category",
                "description": "The status panels break the totals down by device category. Click any panel to jump to that category filtered in Inventory.",
                "position": "top",
                "optional": True,
            },
            {
                "target": ".db-action",
                "title": "Taking Action",
                "description": "The dashboard doesn't edit anything itself. Quick Actions cover the most common operations (add an item, check in/out, triage), and the recent activity feed links straight to the items that changed. Press / from anywhere to jump to search.",
                "position": "left",
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Global Search (all users)
    # ------------------------------------------------------------------
    {
        "id": "search_tour",
        "name": "Global Search",
        "page_pattern": "/search",
        "description": "Search across all device categories at once",
        "enabled": True,
        "group": "inventory",
        "required_access": None,
        "steps": [
            {
                "target": "#global-search-input",
                "title": "Search Input",
                "description": (
                    "Type any keyword to search across every device category "
                    "simultaneously. Results update as you type — serial numbers, "
                    "model names, locations, and notes are all searchable."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": "#search-result-count",
                "title": "Result Count",
                "description": (
                    "This counter shows how many devices matched your query "
                    "across all categories. Use it to gauge whether you need "
                    "to refine your search terms."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#search-results",
                "title": "Search Results",
                "description": (
                    "Matching devices appear here grouped by category. Each row "
                    "shows the device name, serial number, status, and category. "
                    "Use the Edit button on a row to open that device's edit panel."
                ),
                "position": "top",
                "highlight_padding": 6,
                "wait_for": "#search-results",
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Review Queue (editors and above)
    # ------------------------------------------------------------------
    {
        "id": "review_queue_tour",
        "name": "Review Queue",
        "page_pattern": "/review",
        "template": "support.html",
        "description": "Review and approve pending devices waiting to be added to inventory",
        "required_access": "is_editor_or_above",
        "enabled": True,
        "group": "inventory",
        "steps": [
            {
                "target": ".cards",
                "title": "Queue Summary",
                "description": (
                    "These cards show the count of <b>Pending</b>, <b>Approved</b>, "
                    "and <b>Dismissed</b> devices. The counts are filtered to only "
                    "show devices you have permission to review."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": "#review-tabs",
                "title": "Status Tabs",
                "description": (
                    "Switch between <b>Pending</b> (awaiting review), "
                    "<b>Approved</b> (added to inventory), and "
                    "<b>Dismissed</b> (ignored) devices."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            {
                "target": "#review-table",
                "title": "Device Table",
                "description": (
                    "Each row shows a pending device with its MAC address, "
                    "manufacturer (if known), and the inventory category "
                    "suggested by the OUI database."
                ),
                "position": "top",
                "highlight_padding": 6,
            },
            {
                "target": ".table-override-select",
                "title": "Target Category Override",
                "description": (
                    "Before approving, you can change which inventory table "
                    "the device will be added to. The dropdown only shows "
                    "categories you have permission to approve into."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".fl-obtn.ready",
                "title": "Approve & Dismiss",
                "description": (
                    "<b>Approve</b> adds the device to the selected inventory "
                    "table and auto-updates the OUI allowlist. "
                    "<b>Dismiss</b> permanently ignores the device — it won't "
                    "appear in the queue again."
                ),
                "position": "left",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Warranty & RMA (all users)
    # ------------------------------------------------------------------
    {
        "id": "warranty_tour",
        "name": "Warranty & RMA",
        "page_pattern": "/warranty",
        "description": "Understand warranty tracking, internal loaners, and RMA workflows",
        "enabled": True,
        "group": "operations",
        "required_access": None,
        "steps": [
            {
                "target": "h1",
                "title": "Warranty & RMA Tracking",
                "description": (
                    "This page manages device warranties and Return "
                    "Merchandise Authorization (RMA) claims. Use the "
                    "<strong>External</strong> and <strong>Internal</strong> "
                    "tabs to switch between manufacturer warranties and "
                    "cross-team equipment loaners."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": ".warranty-tabs",
                "title": "External vs Internal",
                "description": (
                    "<strong>External Warranties</strong> track manufacturer and "
                    "third-party coverage with expiration dates, tiers, and registration. "
                    "<strong>Internal Loaners</strong> track equipment shared between "
                    "teams — who has it, who owns it, and when it's due back."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            {
                "target": "#warranty-forecast",
                "title": "Quarterly Forecast",
                "description": (
                    "These cards show how many external warranties expire each "
                    "quarter over the next year. Plan ahead for renewals "
                    "and budget allocation."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".header-actions",
                "title": "Action Bar",
                "description": (
                    "Use <strong>+ Add Warranty</strong> or <strong>+ Add Internal "
                    "Loaner</strong> to register new records. Export buttons generate "
                    "Excel or CSV files for reporting."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "table",
                "title": "Warranty Table",
                "description": (
                    "Each row shows a device warranty with vendor, tier, type, "
                    "date range, and registration status. Look for "
                    "<strong>Expired</strong> and <strong>Expiring</strong> "
                    "badges to identify items needing attention."
                ),
                "position": "top",
                "highlight_padding": 4,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Sites & Ownership (all users)
    # ------------------------------------------------------------------
    {
        "id": "sites_tour",
        "name": "Sites & Ownership",
        "page_pattern": "/sites",
        "description": "Manage physical locations and device assignments",
        "required_access": None,
        "enabled": True,
        "group": "operations",
        "steps": [
            {
                "target": "h1",
                "title": "Sites & Ownership",
                "description": (
                    "This page manages physical locations (offices, data centers, "
                    "customer sites) and tracks which devices are assigned where. "
                    "Use it to maintain a clear picture of your deployment footprint."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": ".alert-banner",
                "title": "Overdue Loaners",
                "description": (
                    "When loaner devices are past their expected return date, "
                    "an alert appears here. Click the link to see which devices "
                    "need to be recalled."
                ),
                "position": "bottom",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".fl-cta",
                "title": "Add a Site",
                "description": (
                    "Click <strong>+ Add Site</strong> to register a new location. "
                    "You'll specify the site name, type (office, customer, warehouse, "
                    "etc.), address, and contact information."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".table-section",
                "title": "Sites Table",
                "description": (
                    "Each row shows a site with its type, location, device count, "
                    "and status. Click a site to view its assigned devices and "
                    "manage assignments. Use <strong>Assign Device</strong> to "
                    "link devices to a site."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Try & Buy (all users)
    # ------------------------------------------------------------------
    # /trials has no route in app/routes or app/main.py (READ 2026-09-21).
    # enabled=False keeps the launcher from offering a Start that lands on a
    # page that does not exist. Re-enable when the trials pages ship.
    {
        "id": "trials_tour",
        "name": "Try & Buy",
        "page_pattern": "/trials",
        "description": "Track vendor trials and evaluation workflows",
        "required_access": None,
        "enabled": False,
        "group": "procurement",
        "steps": [
            {
                "target": "h1",
                "title": "Try & Buy Evaluations",
                "description": (
                    "This page tracks vendor trial equipment. Monitor return "
                    "deadlines, record evaluation notes, and make purchase "
                    "or return decisions before trials expire."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": ".alert-banner",
                "title": "Trial Alerts",
                "description": (
                    "Alerts appear when trials are overdue or expiring soon. "
                    "Red alerts mean a trial has passed its return deadline. "
                    "Yellow alerts warn of upcoming deadlines."
                ),
                "position": "bottom",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".btn-primary",
                "title": "Add a Trial",
                "description": (
                    "Click <strong>+ Add Trial</strong> to register new trial "
                    "equipment from a vendor. You'll select the device, set the "
                    "return deadline, and add vendor contact details."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "table",
                "title": "Trials Table",
                "description": (
                    "Each row shows a trial with vendor, device, deadline, and "
                    "evaluation status. Expand a row to see pros, cons, and test "
                    "results. Use <strong>Decide</strong> to record a purchase "
                    "or return decision."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Edge Box Provisioning (sites managers only)
    # ------------------------------------------------------------------
    {
        "id": "provisioning_tour",
        "name": "Edge Box Provisioning",
        "page_pattern": "/provisioning/queue",
        "template": "provisioning.html",
        "description": "Track edge box deployments for pilots and customer sales with pipeline board, grid, and table views",
        "required_access": "has_provisioning_view",
        "enabled": True,
        "group": "fulfillment",
        "steps": [
            {
                "target": ".summary-cards",
                "title": "Provisioning Summary",
                "description": (
                    "These cards show how many edge boxes are currently being "
                    "provisioned, broken down by their current stage. The "
                    "<strong>Overdue</strong> card highlights boxes stuck "
                    "at a stage for more than 7 days."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".prov-filter-bar",
                "title": "Filter & Search",
                "description": (
                    "Use the filter bar to narrow down provisioning records. "
                    "Search by device name, site, or notes. Filter by priority, "
                    "current stage, pipeline bucket, or date status (overdue, "
                    "due soon). Filters apply to all three views."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            {
                "target": ".view-toggle-buttons",
                "title": "Three Views",
                "description": (
                    "Switch between <strong>Board</strong> (pipeline Kanban with "
                    "drag-and-drop), <strong>Table</strong> (detailed queue), and "
                    "<strong>Grid</strong> (sortable list). The board view lets you "
                    "drag cards between buckets to reassign them."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".pipeline-board",
                "title": "Pipeline Board",
                "description": (
                    "The default Board view organizes edge boxes into deployment "
                    "buckets as a Kanban board. <strong>Drag and drop</strong> cards "
                    "between columns to reassign. Each card shows a 7-stage progress "
                    "bar. Click any card to open its <strong>detail page</strong> "
                    "with a full visual pipeline. Switch to <strong>Table</strong> "
                    "or <strong>Grid</strong> views for list-based workflows."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "a[href*='/api/provisioning/export']",
                "title": "Export to Excel",
                "description": (
                    "Click <strong>Export</strong> to download all provisioning "
                    "records as an Excel file. Includes every record with its "
                    "current stage, bucket, priority, assignee, dates, and "
                    "linked customer order — useful for reporting and sharing "
                    "status with stakeholders."
                ),
                "position": "left",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#select-all",
                "title": "Bulk Assign to Order",
                "description": (
                    "In the Table view, check the box in the header to select all visible records "
                    "or pick individual rows. A toolbar appears at the bottom of the screen — "
                    "click <strong>Assign to Order</strong> to link all selected records to a "
                    "customer order at once. Useful for large deployments (50+ boxes)."
                ),
                "position": "right",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Provisioning Detail (sites managers only)
    # ------------------------------------------------------------------
    {
        "id": "provisioning_detail_tour",
        "name": "Provisioning Detail",
        "page_pattern": "/provisioning/*",
        "template": "provisioning_detail.html",
        "description": "Deep dive into a single edge box provisioning record",
        "required_access": "has_provisioning_view",
        "enabled": True,
        "group": "fulfillment",
        "steps": [
            {
                "target": ".prov-detail-pipeline",
                "title": "Stage Pipeline",
                "description": (
                    "This pipeline shows all 7 provisioning stages visually. "
                    "Green boxes are completed (with who and when), the blue "
                    "pulsing box is the current stage, and gray boxes are "
                    "upcoming. Connectors turn green as stages complete."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": ".summary-cards",
                "title": "Quick Summary",
                "description": (
                    "Key metrics at a glance: current stage, priority level, "
                    "days active, completion percentage, target site, and "
                    "assigned team member."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            {
                "target": "[onclick*='scanVerifySerial']",
                "title": "Verify Serial by Scan",
                "description": (
                    "Click the scan icon next to the serial number to open the "
                    "camera. Scan the physical device's barcode to verify it matches "
                    "the record. A <strong>green</strong> toast confirms a match; "
                    "<strong>amber</strong> warns of a mismatch showing both serials."
                ),
                "position": "right",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#metadata-section",
                "title": "Provisioning Details",
                "description": (
                    "View and edit provisioning metadata: dates, pipeline "
                    "bucket, location, and notes. Click <strong>Edit</strong> "
                    "to switch to inline editing mode."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            {
                "target": "#watch-btn",
                "title": "Watch This Record",
                "description": (
                    "Click <strong>Watch this record</strong> to subscribe to "
                    "Slack DM notifications whenever this edge box advances "
                    "to the next stage. Click again to unwatch. Requires "
                    "your account email to be set and the Slack bot configured "
                    "by an admin."
                ),
                "position": "left",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".prov-detail-actions",
                "title": "Actions",
                "description": (
                    "Use <strong>Advance to Next Stage</strong> to complete "
                    "the current stage. <strong>Revert</strong> undoes the "
                    "last completed stage. If a Zendesk ticket is linked, "
                    "changes post automatically."
                ),
                "position": "left",
                "highlight_padding": 6,
            },
            {
                "target": ".audit-timeline",
                "title": "Activity Log",
                "description": (
                    "A timeline of all changes: stage advances, reverts, "
                    "metadata edits, and validation uploads. Each entry "
                    "shows who made the change and when."
                ),
                "position": "left",
                "highlight_padding": 6,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Disposal & EOL (editor+ or can_access_disposal)
    # ------------------------------------------------------------------
    # /disposal has no route in app/routes or app/main.py (READ 2026-09-21).
    # enabled=False keeps the launcher from offering a Start that lands on a
    # page that does not exist. Re-enable when the disposal pages ship.
    {
        "id": "disposal_tour",
        "name": "Disposal & EOL",
        "page_pattern": "/disposal",
        "description": "Track device dispositions, sanitization, and certificates",
        "required_access": "has_disposal_access",
        "enabled": False,
        "group": "operations",
        "steps": [
            {
                "target": "h1",
                "title": "Disposal & End-of-Life",
                "description": (
                    "This page tracks devices that have been recycled, donated, "
                    "sold, or destroyed. Record data sanitization methods and "
                    "upload disposal certificates for compliance."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": ".alert-banner",
                "title": "Sanitization Alerts",
                "description": (
                    "Alerts appear when devices are pending data sanitization. "
                    "All devices should have sanitization completed and "
                    "documented before final disposition."
                ),
                "position": "bottom",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".btn-primary",
                "title": "Record a Disposal",
                "description": (
                    "Click <strong>+ Record Disposal</strong> to document a "
                    "device disposition. Select the device, disposition type "
                    "(recycle, donate, sell, destroy), sanitization method, "
                    "and upload a certificate if available."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "table",
                "title": "Dispositions Table",
                "description": (
                    "Each row shows a disposed device with its disposition type, "
                    "sanitization method, date, and certificate status. The source "
                    "device is automatically set to <strong>Decommissioned</strong> "
                    "when a disposal record is created."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Receive & Scan (editor+ or can_access_receiving)
    # ------------------------------------------------------------------
    # NOTE: receive_tour RE-ENABLED in the tours-overhaul audit (2026-07-12).
    # The intake flow is now exercised daily (scanner Phase 2, PO
    # reconciliation, unit photos all shipped against it) and the copy was
    # rewritten to match shipped behavior: quick-mode confirm tap (H6),
    # wedge loop (H10), PO checklist + tracking auto-select (H16/H17),
    # label photos as tagged unit photos. The progressive wizard steps
    # (#step-details/#step-photo/#step-submit) are optional=True, so the
    # engine skips them cleanly until a scan reveals them.
    {
        "id": "receive_tour",
        "name": "Receive & Scan",
        "page_pattern": "/receive",
        "description": "Walk through the multi-step device intake workflow",
        "required_access": "has_receiving_access",
        "enabled": True,
        "group": "operations",
        "steps": [
            {
                "target": "#step-scan",
                "title": "Receive & Scan",
                "description": (
                    "This page walks you through intake of new equipment — "
                    "scan a barcode with the camera or type the serial, then "
                    "fill in the details. Received components can be assigned "
                    "into a unit right from the success banner."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#step-event",
                "title": "Step 1: Select Event",
                "description": (
                    "Start by selecting or creating a receiving event (shipment). "
                    "If the PO number matches an OEM purchase order, the event "
                    "shows a per-SKU checklist that ticks off as units arrive — "
                    "and scanning the shipment's tracking label selects its "
                    "event automatically."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#step-scan",
                "title": "Step 2: Scan Barcode",
                "description": (
                    "Scan with the camera, a USB scanner, or type the serial — "
                    "the input below stays armed for wedge scanning (watch the "
                    "green dot). Scans are classified server-side: MACs, tracking "
                    "numbers, order numbers, SKUs and serials each get their own "
                    "answer, and duplicates are caught automatically."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#quick-mode-cb",
                "title": "Quick Mode",
                "description": (
                    "Enable <strong>Quick Mode</strong> to receive multiple devices rapidly. "
                    "Recognized units ask for one confirm tap before they're added — "
                    "nothing is ever auto-inserted — and a skipped scan says so. "
                    "Already-received serials show a toast; unknown serials drop "
                    "into the full form. Works with the camera or a USB scanner."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#step-details",
                "title": "Step 3: Device Details",
                "description": (
                    "Select the device category and fill in details. Fields adapt "
                    "based on the category — NAS devices show bay assignment, "
                    "edge boxes show deployment type, etc."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#step-photo",
                "title": "Step 4: Photo & OCR",
                "description": (
                    "Optionally add a photo of the device label. OCR extracts "
                    "serial and model info to auto-fill fields, and the photo is "
                    "kept as a unit photo — tagged to the device on submit, "
                    "visible on its detail page and in its exported dossier."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#step-submit",
                "title": "Step 5: Submit",
                "description": (
                    "Review the details and confirm. The device is added to "
                    "inventory and linked to the receiving event. A success "
                    "banner confirms the intake."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Audit Log (admin/domain admin or can_view_audit_log)
    # ------------------------------------------------------------------
    # NOTE: audit_log_tour is intentionally not repaired here.
    # The original page_pattern (/audit-log) pointed at a JSON API
    # endpoint, not the actual admin audit page. Fixed to /admin/audit
    # so the lint reports against the real page. All 4 step targets
    # (.page-header, .filters-bar, .audit-table, .pagination) are
    # stale vs the redesigned admin_audit.html and need rewriting
    # holistically against the current DOM - deferred to a future
    # audit-page tour-rewrite track. The 4 missing tokens in lint
    # output are expected and serve as a standing reminder.
    # enabled=False protects users from launching the stale tour.
    {
        "id": "audit_log_tour",
        "name": "Audit Log",
        "page_pattern": "/admin/audit",
        "template": "admin_audit.html",
        "description": "Review change history with filters and exports",
        "required_access": "has_audit_access",
        "enabled": False,
        "group": "admin",
        "steps": [
            {
                "target": ".page-header",
                "deferred": True,
                "deferred_reason": "Deferred per commit 2965087 — .page-header pending audit-page rewrite track.",
                "title": "Audit Log",
                "description": (
                    "The audit log records every create, update, and delete "
                    "action across all device categories. Use it for compliance "
                    "audits, change tracking, and accountability."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
            {
                "target": ".filters-bar",
                "deferred": True,
                "deferred_reason": "Deferred per commit 2965087 — .filters-bar pending audit-page rewrite track.",
                "title": "Filters",
                "description": (
                    "Filter the log by search text, device category, action type "
                    "(create/update/delete), user, and date range. Apply filters "
                    "to narrow down to specific changes."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".audit-table",
                "deferred": True,
                "deferred_reason": "Deferred per commit 2965087 — .audit-table pending audit-page rewrite track.",
                "title": "Log Entries",
                "description": (
                    "Each row shows who made a change, when, what action was "
                    "taken, and which device was affected. Expand a row to see "
                    "the specific field changes (old → new values)."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".pagination",
                "deferred": True,
                "deferred_reason": "Deferred per commit 2965087 — .pagination pending audit-page rewrite track.",
                "title": "Pagination & Export",
                "description": (
                    "Navigate through pages of results or export the filtered "
                    "log to Excel for offline review. Large audit histories "
                    "are paginated for performance."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },
    # --- Vendor Profiles Tour ---
    {
        "id": "vendor_tour",
        "name": "Vendor Profiles",
        "page_pattern": "/vendors",
        "description": "Keep all your vendor contacts, OEM notes, and procurement analytics in one place",
        "required_access": "is_editor_or_above",
        "enabled": True,
        "group": "procurement",
        "steps": [
            {
                "target": "h1",
                "title": "Vendor Profiles",
                "description": (
                    "This page lists all vendors from your inventory. "
                    "Profiles with contact info appear at the top. "
                    "Vendors without profiles are shown below so you can add them."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            {
                "target": ".table-section",
                "title": "Click a Vendor to See Details",
                "description": (
                    "Click any vendor name to open its detail page. "
                    "There you'll find the full contact card, procurement analytics "
                    "(devices purchased, warranties, RMA claims), and Try & Buy history."
                ),
                "position": "right",
                "highlight_padding": 4,
            },
            {
                "target": "[onclick='openAddModal()']",
                "title": "Add a Vendor Profile",
                "description": (
                    "Click '+ Add Vendor' to create a profile. "
                    "The vendor name must match exactly what's in the inventory "
                    "'Vendor' field — the match is case-insensitive. "
                    "Use 'Auto-Create All' to seed profiles for every known vendor at once."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
        ],
    },
    # ------------------------------------------------------------------
    # Fulfillment — comprehensive tour (provisioning viewers+)
    # ------------------------------------------------------------------
    # NOTE: orders_tour is intentionally not repaired here.
    # Fulfillment and deployment pages are scheduled for a full revamp;
    # the tour will be rewritten holistically at that time. Current rot
    # (.arch-toggle is gone; replaced by .arch-head in the live DOM)
    # is left as-is so the revamp owns the rewrite end-to-end.
    # enabled=False protects users from launching the stale tour.
    # SUPERSEDED 2026-07-12 by fulfillment_board_tour (new key per policy —
    # keys are never reused). Kept disabled for the record.
    {
        "id": "orders_tour",
        "name": "Fulfillment",
        "page_pattern": "/fulfillment",
        "description": "Complete guide to the fulfillment Kanban — orders, deployments, shipping, and stock",
        "required_access": "has_provisioning_view",
        "enabled": False,
        "group": "fulfillment",
        "steps": [
            # ── Page overview ──────────────────────────────────────
            {
                "target": ".fl-header",
                "title": "Fulfillment Page",
                "description": (
                    "This page tracks every customer order from initial request "
                    "through hardware delivery and on-site installation. Orders "
                    "flow left-to-right across a Kanban board. Each card represents "
                    "one order with its linked provisioning records and shipping status."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            # ── Scan to Find button ──────────────────────────────
            {
                "target": "[onclick='scanToFind()']",
                "title": "Scan to Find Device",
                "description": (
                    "Click <strong>Scan</strong> to open the camera barcode scanner. "
                    "Scan any device serial — if it's in inventory, a toast appears "
                    "with a <strong>View</strong> button linking to its provisioning record. "
                    "If the serial isn't recognized, you'll get a <strong>Receive</strong> "
                    "link to add it to inventory."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            # ── In-House / OEM toggle ──────────────────────────────
            {
                "target": ".mode-toggle",
                "title": "In-House / OEM Toggle",
                "description": (
                    "Switch between <strong>In-House</strong> (orders we fulfill directly) "
                    "and <strong>OEM</strong> (orders fulfilled by OEM partners). "
                    "Each view has its own Kanban board with independent columns and stats."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Command band stats ─────────────────────────────────
            {
                "target": ".cmd-band .cb-stats",
                "title": "Quick Stats",
                "description": (
                    "Four live counters at a glance:<br>"
                    "<strong>Active</strong> — total orders in the pipeline<br>"
                    "<strong>Overdue</strong> — orders past their due date (click to see list)<br>"
                    "<strong>Due Soon</strong> — orders due within 14 days (click to see list)<br>"
                    "<strong>Stock</strong> — available edge boxes vs. total in inventory<br>"
                    "Click any stat to open its detail panel on the right."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Search bar ─────────────────────────────────────────
            {
                "target": "#cb-search",
                "title": "Search Orders",
                "description": (
                    "Type to filter cards instantly by order number, customer name, "
                    "or sales engineer. Cards that don't match are hidden. "
                    "Press the × button or clear the field to reset."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Coverage filter ────────────────────────────────────
            {
                "target": "#btn-coverage",
                "title": "Coverage Filter",
                "description": (
                    "Filter the board by sales engineer coverage area. "
                    "Click <strong>Coverage</strong> to open a multi-select panel — "
                    "check one or more engineers to show only their orders. "
                    "A badge shows how many filters are active. "
                    "Click <strong>Clear</strong> to remove all coverage filters."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Pipeline filter bar ────────────────────────────────
            {
                "target": "#pfb-active",
                "title": "Pipeline Filter Bar",
                "description": (
                    "Shows the five pipeline stages as clickable dots:<br>"
                    "<strong>Approved PO → Sourcing → Building → Validation → Shipping</strong><br>"
                    "Click a stage to dim all other columns and focus on that one. "
                    "Click again to reset. The count badge on each dot updates live."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Kanban grid ────────────────────────────────────────
            {
                "target": "#kanban-ih",
                "title": "Order Kanban Board",
                "description": (
                    "Five columns show active orders flowing through the pipeline. "
                    "Each column represents a stage. Drag cards between columns to "
                    "change an order's status (the change saves automatically). "
                    "Empty columns show a placeholder card."
                ),
                "position": "top",
                "highlight_padding": 6,
            },
            # ── Single order card anatomy ──────────────────────────
            {
                "target": ".o-card",
                "title": "Order Card",
                "description": (
                    "Each card shows:<br>"
                    "• <strong>Order number</strong> and <strong>customer name</strong><br>"
                    "• Sales engineer (or 'Unassigned')<br>"
                    "• <strong>Direct / Integrator</strong> toggle (click to change deployment type)<br>"
                    "• Due date with urgency color coding (green/amber/red/purple)<br>"
                    "• SKU model chip with required quantity<br>"
                    "• Mini-steps progress bar showing provisioning completion<br>"
                    "Click a card to open the detail slide panel on the right."
                ),
                "position": "right",
                "highlight_padding": 4,
                "optional": True,
            },
            # ── Card urgency colors ────────────────────────────────
            {
                "target": ".o-card",
                "title": "Urgency Color Coding",
                "description": (
                    "The left border on each card indicates urgency:<br>"
                    "<span style='color:#22c55e'>■</span> <strong>Green</strong> — on track (30+ days)<br>"
                    "<span style='color:#f59e0b'>■</span> <strong>Amber</strong> — due within 14 days<br>"
                    "<span style='color:#ef4444'>■</span> <strong>Red</strong> — due within 7 days<br>"
                    "<span style='color:#9333ea'>■</span> <strong>Purple</strong> — overdue<br>"
                    "These same colors appear in the due date chip."
                ),
                "position": "left",
                "highlight_padding": 4,
                "optional": True,
            },
            # ── Deployment pipeline ────────────────────────────────
            {
                "target": ".deploy-section",
                "title": "Deployment Pipeline",
                "description": (
                    "Below the order Kanban is the <strong>Deployment Pipeline</strong> — "
                    "tracking orders after they ship. Stages:<br>"
                    "<strong>Scheduled → In Transit → On-Site → Installing → Complete</strong><br>"
                    "Cards here show deployment records with mini-step progress. "
                    "This section populates as orders move to deployment."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
            # ── Archived section ───────────────────────────────────
            {
                "target": ".arch-toggle",
                "deferred": True,
                "deferred_reason": "Deferred per commit 6bdd22a — .arch-toggle restoration pending fulfillment/deployment revamp track.",
                "title": "Archived Orders",
                "description": (
                    "Click to expand/collapse completed orders. "
                    "Three columns: <strong>Shipped</strong>, <strong>Delivered</strong>, "
                    "and <strong>Installed</strong>. These are read-only — orders move "
                    "here automatically when their status changes."
                ),
                "position": "top",
                "highlight_padding": 6,
            },
            # ── Side panel: Overdue ────────────────────────────────
            {
                "target": "#stat-overdue",
                "title": "Overdue Panel",
                "description": (
                    "Click the <strong>Overdue</strong> stat to slide open a panel "
                    "listing every order past its due date. Each row shows the order "
                    "number, customer, and how many days overdue. Use the "
                    "<strong>Jump</strong> button to scroll to that order's column."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Side panel: Stock ──────────────────────────────────
            {
                "target": "#stat-stock",
                "title": "Stock Panel",
                "description": (
                    "Click the <strong>Stock</strong> stat to see inventory by SKU model. "
                    "Each tile shows the SKU name, available count, and percentage of "
                    "total stock. A yellow 'No SKU' tile appears for edge boxes without "
                    "a model assignment."
                ),
                "position": "bottom",
                "highlight_padding": 6,
            },
            # ── Slide panel (detail) ───────────────────────────────
            {
                "target": "#ap",
                "title": "Order Detail Panel",
                "description": (
                    "When you click a card, a detail panel slides in from the right "
                    "with three tabs:<br>"
                    "<strong>Assign Boxes</strong> — select unassigned edge boxes to link to this order<br>"
                    "<strong>View Status</strong> — see provisioning progress per device<br>"
                    "<strong>Ship Order</strong> — enter carrier, tracking number, and dates<br>"
                    "Click <strong>View Full Order →</strong> to open the full order detail page."
                ),
                "position": "left",
                "highlight_padding": 6,
                "optional": True,
            },
            # ── Assign Boxes tab ───────────────────────────────────
            {
                "target": "#pane-assign",
                "title": "Assign Boxes Tab",
                "description": (
                    "Shows unassigned edge boxes that match the order's SKU requirements. "
                    "Click rows to select them (they highlight blue), then click "
                    "<strong>Assign</strong> to link them to this order. "
                    "Use the SKU filter chips or search box to narrow the list. "
                    "The counter at the bottom tracks how many you've selected."
                ),
                "position": "left",
                "highlight_padding": 4,
                "optional": True,
            },
            # ── Ship tab ───────────────────────────────────────────
            {
                "target": "#pane-ship",
                "title": "Ship Order Tab",
                "description": (
                    "Choose between <strong>Shipped</strong> (carrier delivery) "
                    "or <strong>Transferred</strong> (hand-delivered by a sales engineer). "
                    "For shipped: enter carrier name, tracking number, and address. "
                    "For transferred: enter the recipient and handoff date. "
                    "Click <strong>Save Ship Details</strong> to update the order."
                ),
                "position": "left",
                "highlight_padding": 4,
                "optional": True,
            },
            # ── New Order button ───────────────────────────────────
            {
                "target": "[onclick='openNewOrderModal()']",
                "title": "Create a New Order",
                "description": (
                    "Click <strong>+ New Order</strong> to open the order form. "
                    "Fill in customer name, sales engineer, due date, "
                    "deployment type, and SKU model(s) with quantities. "
                    "The order will appear in the 'Approved PO' column once saved. "
                    "This button is only visible to users with provisioning management access."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            # ── Unlinked provisioning notice ───────────────────────
            {
                "target": ".unlinked-notice",
                "title": "Unlinked Provisioning",
                "description": (
                    "This notice appears when provisioning records exist that aren't "
                    "linked to any order. Click the link to open the provisioning queue "
                    "and assign them. The count updates in real time."
                ),
                "position": "bottom",
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Order Detail (provisioning viewers+)
    # ------------------------------------------------------------------
    # NOTE: order_detail_tour is intentionally left disabled here.
    # Two reasons. (1) The customer-orders workflow has never been exercised
    # with real data (customer_orders is empty); enabling a guided tour of an
    # unproven path risks misleading users. (2) This tour is in the
    # fulfillment group, which is scheduled for the same full revamp that
    # already defers orders_tour - the detail tour should be rewritten
    # holistically alongside that work rather than enabled piecemeal now.
    # The tour's 5 step targets are believed accurate against the current
    # order_detail.html but were not browser-verified live (no order to load).
    # Re-enable as part of the fulfillment revamp once /orders is in real use.
    # enabled=False protects users from launching the unproven tour.
    # SUPERSEDED 2026-07-12 by order_page_tour (new key per policy —
    # keys are never reused). Kept disabled for the record.
    {
        "id": "order_detail_tour",
        "name": "Order Detail",
        "page_pattern": "/orders/*",
        "template": "order_detail.html",
        "description": "Deep dive into a single customer order — SKUs, provisioning links, and OEM purchase orders",
        "required_access": "has_provisioning_view",
        "enabled": False,
        "group": "fulfillment",
        "steps": [
            {
                "target": ".summary-cards",
                "title": "Order Overview",
                "description": (
                    "Six quick-glance cards: Salesforce Order ID, Sales Engineer, "
                    "Due Date, Deployment Type, number of linked Provisioning "
                    "records, and OEM Purchase Orders. All key fields at a glance."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#avail-tbody",
                "title": "SKU Availability",
                "description": (
                    "For each SKU model in the order, the app checks live inventory "
                    "to show how many edge boxes are available (not already assigned "
                    "to an active provisioning record). Green = enough stock, "
                    "yellow = partial, red = none available."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "table",
                "title": "Linked Provisioning Records",
                "description": (
                    "Each row is an edge box being provisioned for this order. "
                    "Shows device name, current stage, assignee, priority, and "
                    "completion status. Click any row to open that provisioning "
                    "detail page. Use the <strong>+ Link</strong> button to "
                    "attach additional provisioning records."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": "#add-po-modal",
                "title": "OEM Purchase Orders",
                "description": (
                    "Track purchase orders placed with OEM vendors for this "
                    "customer order. Each PO records the vendor, PO number, "
                    "SKU model, quantity ordered, and current status "
                    "(pending → confirmed → shipped → received)."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#status-badge",
                "title": "Advance Order Status",
                "description": (
                    "Use the <strong>Update Status</strong> button to advance "
                    "the order through its pipeline: "
                    "New → Sourcing → Building → Testing → Shipped → Delivered → Installed. "
                    "Pre- and post-install survey notes can be added at any stage."
                ),
                "position": "left",
                "highlight_padding": 8,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Vendor Detail Profile (editor+)
    # ------------------------------------------------------------------
    {
        "id": "vendor_detail_tour",
        "name": "Vendor Detail",
        "page_pattern": "/vendors/*",
        "template": "vendor_detail_profile.html",
        "description": "Contact card, quality score, procurement analytics, and device history for a single vendor",
        "required_access": "is_editor_or_above",
        "enabled": True,
        "group": "procurement",
        "steps": [
            {
                "target": ".vendor-grid",
                "title": "Vendor Overview",
                "description": (
                    "Left column shows contact information (name, email, phone, website) "
                    "and the vendor's quality score. Right column shows procurement "
                    "analytics pulled from your inventory data."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
            {
                "target": ".quality-ring",
                "title": "Quality Score",
                "description": (
                    "The quality score (0–100) is auto-calculated from warranty "
                    "claim rates and trial success rates. Green = Excellent (80+), "
                    "Blue = Good (60+), Yellow = Needs Review (below 60). "
                    "No manual entry required — it updates automatically."
                ),
                "position": "right",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".stat-grid",
                "title": "Procurement Analytics",
                "description": (
                    "Key metrics for this vendor: total devices purchased, "
                    "total spend, active warranties, RMA claim count, "
                    "and active Try & Buy trials — all drawn from your "
                    "existing inventory records."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".table-section",
                "title": "Device & Trial History",
                "description": (
                    "Full list of devices sourced from this vendor across all "
                    "categories, plus any active or past Try & Buy trials. "
                    "Use the <strong>Edit</strong> button in the contact card "
                    "to update vendor profile details."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # User Management (user management access)
    # ------------------------------------------------------------------
    {
        "id": "admin_users_tour",
        "name": "User Management",
        "page_pattern": "/admin/users",
        "template": "admin_users.html",
        "description": "Create accounts, assign roles and departments, and configure granular per-user permissions",
        "required_access": "has_user_management",
        "enabled": True,
        "group": "admin",
        "steps": [
            {
                "target": "#users-add-btn",
                "title": "Create a User",
                "description": (
                    "Fill in username, display name, temporary password, and role, "
                    "then click <strong>Create User</strong>. New users are prompted "
                    "to change their password on first login."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
            {
                "target": ".user-card__dept",
                "title": "Department Assignment",
                "description": (
                    "Each user is assigned to a department (Hardware, QA, Support, etc.). "
                    "Departments serve as permission templates — users inherit the department's "
                    "defaults. The dept label on each user card shows the current assignment. "
                    "Click any user card now to open the drawer — the next step covers what's inside."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".ud-perm-row",
                "title": "Permission Toggles",
                "description": (
                    "Inside the user drawer, the permission toggles are organized into groups: "
                    "Domain Admin, Page Access, System, and Provisioning. Each toggle is ON or OFF "
                    "per user. Department defaults apply when a user's toggle hasn't been explicitly set."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": "[class*=\"user-card__tag--role-\"]",
                "title": "Roles & Actions",
                "description": (
                    "The role badge shows each user's base role (Admin, Editor, "
                    "Viewer, etc.). Use the action buttons to disable/re-enable "
                    "accounts, reset passwords, change roles, or delete users."
                ),
                "position": "left",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Intune Sync (system admin)
    # ------------------------------------------------------------------
    # NOTE: admin_intune_tour is intentionally left disabled here.
    # Three issues, all needing resolution before enabling:
    # (1) The Intune integration is not configured (Tenant/Client/Secret
    #     creds are all Missing), so the "Test Connection" and "Sync Now"
    #     buttons that step 3 describes do not render on the page at all -
    #     the tour would walk users to controls that do not exist yet.
    # (2) Selector mis-targeting: step 2 ("Sync History") uses a bare
    #     .table-section and resolves to the FIRST such div ("Credentials
    #     Not Configured"), not Sync History; step 3 ("Test & Sync") uses a
    #     bare "button" and grabs the first <button> on the page (a nav/icon
    #     button), not the intended action buttons. Both need id-based
    #     targets like the procurement_tour fix.
    # (3) The tour step-1 text was corrected ("on the server"), but
    #     admin_intune.html ITSELF still carries stale "NUC"/"Chris"
    #     wording - a separate template-content fix tracked separately.
    # Re-enable once Intune is configured and the tour is rewritten/retargeted
    # against the live, connected page.
    # enabled=False protects users from launching the broken tour.
    {
        "id": "admin_intune_tour",
        "name": "Intune Device Sync",
        "page_pattern": "/admin/intune",
        "template": "admin_intune.html",
        "description": "Configure Microsoft Intune sync to automatically import managed Windows devices",
        "required_access": "has_system_admin",
        "enabled": False,
        "group": "admin",
        "steps": [
            {
                "target": ".summary-cards",
                "title": "Connection Status",
                "description": (
                    "Four cards show whether the required Azure credentials are "
                    "configured: Tenant ID, Client ID, Client Secret, and Auto-Sync "
                    "mode. All four must be green before syncing. "
                    "Add credentials to the <code>.env</code> file on the server."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".table-section",
                "title": "Sync History",
                "description": (
                    "Every sync run is logged here: when it ran, who triggered it, "
                    "how many devices were found / added / updated / skipped, "
                    "and whether it succeeded or errored. "
                    "New devices are added to the <strong>Computers</strong> "
                    "category with <code>discovered_by=intune_import</code>."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": "button",
                "title": "Test & Sync",
                "description": (
                    "<strong>Test Connection</strong> verifies the Azure credentials "
                    "without importing any data. "
                    "<strong>Sync Now</strong> runs a full import immediately. "
                    "Set <code>INTUNE_AUTO_SYNC=true</code> in <code>.env</code> "
                    "to enable nightly automatic syncs at 2 AM."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Zendesk Integration (system admin)
    # ------------------------------------------------------------------
    {
        "id": "admin_zendesk_tour",
        "name": "Zendesk Integration",
        "page_pattern": "/admin/zendesk",
        "template": "admin_zendesk.html",
        "description": "Configure and test the Zendesk connection for ticket linking on provisioning records",
        "required_access": "has_system_admin",
        "enabled": True,
        "group": "admin",
        "steps": [
            {
                "target": "#connection-status",
                "title": "Connection Status",
                "description": (
                    "Shows whether the Zendesk subdomain, email, and API token "
                    "are configured and working. Click <strong>Test Connection</strong> "
                    "to verify live connectivity. Credentials live in "
                    "<code>.env</code> on the server."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
            {
                "target": "#orgs-container",
                "title": "Organizations",
                "description": (
                    "Click <strong>Load Organizations</strong> to pull the list of "
                    "Zendesk organizations. These are the customer/company entries "
                    "that appear in the provisioning detail page's Customer/Organization "
                    "field for reference."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#tickets-container",
                "title": "Recent Tickets",
                "description": (
                    "Load recent Zendesk tickets to verify the connection is "
                    "pulling live data. On provisioning detail pages, admins can "
                    "link a specific Zendesk ticket ID — stage advances then "
                    "auto-comment on that ticket."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Spreadsheet Sync (system admin)
    # ------------------------------------------------------------------
    {
        "id": "admin_spreadsheet_tour",
        "name": "Spreadsheet Sync",
        "page_pattern": "/admin/spreadsheet-sync",
        "template": "admin_spreadsheet_sync.html",
        "description": "Upload the Excel master inventory file to preview and apply bulk device updates",
        "required_access": "has_system_admin",
        "enabled": True,
        "group": "admin",
        "steps": [
            {
                "target": "#file-input",
                "title": "Upload Excel File",
                "description": (
                    "Choose the master inventory Excel file (.xlsx). "
                    "The file is parsed across every sheet in the workbook — no changes are "
                    "made to the database yet. A preview of what would change "
                    "is generated first."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
            {
                "target": "#stats-summary",
                "title": "Change Summary",
                "description": (
                    "After uploading, a summary bar shows how many records will "
                    "be <strong style='color:#27ae60'>Added</strong> (new devices), "
                    "<strong style='color:#f39c12'>Updated</strong> (existing devices with changes), "
                    "or <strong style='color:#95a5a6'>Skipped</strong> (no changes detected)."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".tabs",
                "title": "Review Changes by Type",
                "description": (
                    "Switch between <strong>Adds</strong>, <strong>Updates</strong>, "
                    "and <strong>Skips</strong> tabs to review every record before "
                    "committing. The Updates tab shows old → new field changes. "
                    "Review carefully — this modifies live inventory data."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#apply-btn",
                "title": "Apply to Database",
                "description": (
                    "Once you've reviewed the preview, click "
                    "<strong>Apply Changes to Database</strong> to commit all "
                    "adds and updates. This action is logged in the audit trail. "
                    "There is no undo — verify the preview first."
                ),
                "position": "top",
                "highlight_padding": 6,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # OUI Reference (editor+)
    # ------------------------------------------------------------------
    {
        "id": "admin_oui_tour",
        "name": "OUI Reference",
        "page_pattern": "/admin/oui",
        "template": "admin_oui.html",
        "description": "Hardware manufacturer registry used during pending-device approval to identify a MAC address's manufacturer and suggest a category",
        "required_access": "is_editor_or_above",
        "enabled": True,
        "group": "admin",
        "steps": [
            {
                "target": ".summary-cards",
                "title": "OUI Reference Overview",
                "description": (
                    "Three summary numbers: total registered manufacturers, "
                    "total OUI prefixes tracked, and how many inventory devices "
                    "were matched to an OUI. When a pending device is approved, "
                    "the OUI lookup uses this database to identify its manufacturer from the MAC address."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".vendor-group-header",
                "title": "Manufacturer Groups",
                "description": (
                    "Each row is a hardware manufacturer. Click to expand and "
                    "see individual OUI prefixes (the first 3 bytes of a MAC address) "
                    "and which inventory category each prefix maps to. "
                    "When a pending device with a matching prefix is approved, "
                    "the OUI mapping auto-categorizes it into the right inventory table."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": "#add-oui-form",
                "title": "Add a Manufacturer",
                "description": (
                    "Admins can add new OUI prefixes here. Enter the 6-character "
                    "hex prefix (e.g. <code>AABBCC</code>), manufacturer name, "
                    "and the inventory category it maps to. New entries take "
                    "effect on the next network scan."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Concept: Where is data stored?
    # ------------------------------------------------------------------
    {
        "id": "concept_data_storage_tour",
        "name": "Where Is My Data Stored?",
        "page_pattern": "/dashboard",
        "description": "Explains how and where all inventory data is saved, backed up, and who can change it",
        "required_access": None,
        "enabled": True,
        "group": "onboarding",
        "steps": [
            {
                "center": True,
                "title": "Where Is the Data?",
                "description": (
                    "All inventory data lives in a <strong>PostgreSQL database</strong> "
                    "on the QA server in the lab, running alongside the app in Docker. "
                    "Nothing is stored in the cloud — the app runs entirely on-site, "
                    "and the database files live on the server's data drive, separate "
                    "from the app code."
                ),
                "optional": True,
            },
            {
                "center": True,
                "title": "How Is It Backed Up?",
                "description": (
                    "Every night a full database snapshot plus all uploaded files "
                    "(receipts, photos, certification reports) are written to a backup "
                    "folder on the server, and a second copy is pulled to an off-box "
                    "machine automatically. Restores are tested against a scratch "
                    "database on a monthly habit, and the Admin → Maintenance page "
                    "shows a warning if backups ever go stale."
                ),
                "optional": True,
            },
            {
                "center": True,
                "title": "How Does Data Get In?",
                "description": (
                    "Data enters the system two ways: "
                    "<strong>(1) Manually</strong> — team members add or edit devices directly in the app. "
                    "<strong>(2) Spreadsheet Import</strong> — an Excel master inventory file can be uploaded under Admin → Spreadsheet Sync to bulk-load or update records."
                ),
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Concept: How do roles and permissions work?
    # ------------------------------------------------------------------
    {
        "id": "concept_roles_permissions_tour",
        "name": "How Do Roles & Permissions Work?",
        "page_pattern": "/dashboard",
        "description": "Explains the role hierarchy, what each role can do, and how department permissions layer on top",
        "required_access": None,
        "enabled": True,
        "group": "onboarding",
        "steps": [
            {
                "target": ".sx-nav__user-role",
                "title": "Your Role",
                "description": (
                    "Every user has a <strong>base role</strong> shown in the sidebar. "
                    "Roles from most to least access: "
                    "<strong>Admin</strong> → <strong>Editor</strong> → <strong>Viewer</strong>. "
                    "Specialty roles like <em>Procurement Admin</em> or <em>Sites Manager</em> "
                    "unlock specific sections (financial data, provisioning, site management) "
                    "on top of a base role. Your role is set by an admin in User Management."
                ),
                "position": "right",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "center": True,
                "title": "Departments as Templates",
                "description": (
                    "Users belong to departments (Hardware, QA, Support, etc.). "
                    "Each department has a default set of permissions. "
                    "When you're added to a department, you automatically inherit those defaults — "
                    "no manual setup required. "
                    "Admins manage department defaults under Admin → People → Departments."
                ),
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "center": True,
                "title": "Per-User Overrides",
                "description": (
                    "Department permissions are a starting point. "
                    "Admins can override individual permissions per user. "
                    "Each permission is effectively in one of three states: "
                    "Inherit (follow the department default), ON (force grant), or OFF (force block). "
                    "No user needs to be moved to a different department just for one exception."
                ),
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },

    # --- Team Management Tour ---
    {
        "id": "department_management_tour",
        "name": "Department Management",
        "page_pattern": "/admin/departments",
        "template": "admin_departments.html",
        "description": "Manage departments as permission templates. Set defaults that flow to all assigned users.",
        "required_access": "has_user_management",
        "enabled": True,
        "group": "admin",
        "steps": [
            {
                "target": "#depts-add-btn",
                "title": "Create a Department",
                "description": (
                    "Click here to create a new department. Give it a name and description, "
                    "then set its default permissions. Users assigned to this department will "
                    "inherit these defaults."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": ".dept-card__heat",
                "title": "Department Permissions",
                "description": (
                    "Each department card shows a heatmap of its permission defaults — green "
                    "means granted, gray means blocked. It's an at-a-glance summary; change the "
                    "actual values from the drawer."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".dept-card__meta",
                "title": "Department Members",
                "description": (
                    "Each card shows a member count for that department. Click any card to open "
                    "the management drawer, where you can edit the name, description, and toggle "
                    "each permission default."
                ),
                "position": "bottom",
                "highlight_padding": 4,
                "optional": True,
            },
        ],
    },
    # ------------------------------------------------------------------
    # Error Log (admin only)
    # ------------------------------------------------------------------
    {
        "id": "error_log_tour",
        "name": "Error Log",
        "page_pattern": "/admin/errors",
        "template": "admin_errors.html",
        "description": "Monitor frontend and backend errors captured automatically",
        "required_access": "has_system_admin",
        "enabled": True,
        "group": "admin",
        "steps": [
            {
                "target": ".summary-cards",
                "title": "Error Summary",
                "description": (
                    "These cards show the total error count and a breakdown of "
                    "frontend vs backend errors in the last 24 hours. "
                    "Green means zero recent errors."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": "#error-table",
                "title": "Error Timeline",
                "description": (
                    "Recent errors sorted newest first. Click any row to see the "
                    "full stack trace, browser info, and error fingerprint. "
                    "Use the source filter above to narrow by frontend or backend."
                ),
                "position": "top",
                "highlight_padding": 4,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Inventory (all users)
    # ------------------------------------------------------------------
    {
        "id": "inventory_tour",
        "name": "Inventory",
        "page_pattern": "/inventory",
        "description": "A walkthrough of the Inventory page \u2014 tiles, search, the device table, and quick view.",
        "required_access": None,
        "enabled": True,
        "group": "inventory",
        "steps": [
            {
                "target": ".inv-tiles",
                "title": "Summary Tiles",
                "description": (
                    "These tiles show a live count of every device category in the system. "
                    "Click one or more tiles to filter the table below to that category. "
                    "Click again to deselect."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": "#inv-search-input",
                "title": "Search",
                "description": (
                    "Type here to search across all visible devices by name, serial number, "
                    "MAC address, or any other field. Results update as you type."
                ),
                "position": "bottom",
                "highlight_padding": 8,
            },
            {
                "target": "#inv-tbody",
                "title": "Device Table",
                "description": (
                    "All devices matching your current filters are listed here. Each row shows the "
                    "device category, name, serial number, status, and MAC address. Select multiple "
                    "devices using the checkboxes to reveal bulk export, status change, and site "
                    "assignment options."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "wait_for": "#inv-tbody tr",
                "wait_prompt": "Click any category tile above to load devices into the table, then the tour will continue automatically.",
            },
            {
                "target": ".qv-panel",
                "title": "Quick View",
                "description": (
                    "This panel shows a read-only summary of the selected device. Use the Edit "
                    "button to make changes or View Full Details to open the complete device record."
                ),
                "position": "bottom",
                "highlight_padding": 8,
                "wait_for": "#qv-overlay",
                "wait_prompt": "Click any device row to open the quick view panel, then the tour will continue automatically.",
            },
        ],
    },

    # ------------------------------------------------------------------
    # Asset Triage (editors and above)
    # ------------------------------------------------------------------
    {
        "id": "asset_triage_tour",
        "name": "Asset Triage Tour",
        "description": "How to find and fix inventory items that are missing role-required fields.",
        "page_pattern": "/triage",
        "enabled": True,
        "required_access": "is_editor_or_above",
        "group": "inventory",
        "steps": [
            {
                "title": "What Is Asset Triage?",
                "description": "This page surfaces inventory items that are missing role-required fields. Fix them here and they are ready to deploy.",
                "target": ".page-header",
            },
            {
                "title": "Per-Role Gap Counts",
                "description": "Each tab represents a role. The badge on the tab is the number of items missing fields for that role. Switch tabs to focus on one role at a time.",
                "target": ".trg-tabs",
            },
            {
                "title": "Sort and Pagination",
                "description": "Sort by oldest, gap count, or name. Per page controls how many rows you see at once.",
                "target": ".trg-controls",
            },
            {
                "title": "The Gap Table",
                "description": "Each row is an item that needs attention. The chip on the right side of each row shows how many fields are still missing.",
                "target": ".trg-table",
                "wait_for": ".trg-row",
                "optional": True,
            },
            {
                "title": "Edit an Item",
                "description": "Click any row to open the edit drawer and fill in the missing fields. Or click the chevron on the left to expand a quick preview without leaving the page.",
                "target": ".trg-row",
                "optional": True,
            },
        ],
    },
    # ==================================================================
    # COMMIT-4 tours (2026-07-12) — copy approved via chat review;
    # deviations from the approved outlines are template-truth fixes,
    # each recorded in the commit message.
    # ==================================================================

    # ------------------------------------------------------------------
    # Deployment Map (map access; kiosk excluded by the /api middleware)
    # NOTE: the sidebar link to /map/ is currently commented out in
    # base.html — the launcher's Start button is the discoverable path.
    # ------------------------------------------------------------------
    {
        "id": "map_tour",
        "name": "Deployment Map",
        "page_pattern": "/map",
        "template": "map.html",
        "description": "The live unit map — color modes, click-to-filter charts, and visibility curation",
        "required_access": "has_map_access",
        "enabled": True,
        "group": "operations",
        "steps": [
            {
                # #map is absolutely positioned inside this layout parent;
                # anchoring the parent measures reliably.
                "target": ".mp-maparea",
                "title": "The Live Map",
                "description": (
                    "Every deployed unit, colored by the mode you pick in the "
                    "rail. Dots cluster when you zoom out; click any dot for "
                    "its details. Units hidden by curation or on sensitive "
                    "orders don't appear."
                ),
                "position": "left",
                "optional": True,
            },
            {
                "title": "Three Levels of Visibility",
                "description": (
                    "Editors can hide a single unit, a whole site, or an "
                    "entire customer from a dot's popup — hiding a site "
                    "removes every unit there, hiding a customer removes all "
                    "of theirs. Units on sensitive orders are hidden "
                    "automatically for accounts without sensitive access."
                ),
                "center": True,
                "optional": True,
            },
            {
                "target": "#mp-mode",
                "title": "Color Units By",
                "description": (
                    "Switch what the colors mean: Deal Type, Unit Type, or "
                    "Status. The legend follows the mode, and your pick is "
                    "remembered."
                ),
                "position": "right",
                "optional": True,
            },
            {
                "target": "#mp-deal-bars",
                "title": "Charts That Filter",
                "description": (
                    "These bars aren't just a chart — click one to hide that "
                    "deal type from the map, click again to bring it back. "
                    "Filtered rows dim so you can see what's excluded."
                ),
                "position": "right",
                "optional": True,
            },
            {
                "title": "What a Dot Tells You",
                "description": (
                    "Clicking a dot opens a popup with the customer and site, "
                    "the unit and its serial, a deal badge, status, deployed "
                    "and due-back dates, and a link to the full item page."
                ),
                "center": True,
                "optional": True,
            },
            {
                "title": "Built for the Lobby Too",
                "description": (
                    "A dedicated kiosk role can show this map on a wall "
                    "display: it stays signed in, can pan and filter, but "
                    "can't change data or leave the map."
                ),
                "center": True,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Item Detail (all users) — merged containment + photos + dossier
    # Wildcard pattern: the launcher shows an "open any item first" hint
    # instead of a Start button; the tour anchors read-mode sections.
    # ------------------------------------------------------------------
    {
        "id": "item_detail_tour",
        "name": "Item Detail",
        "page_pattern": "/items/*",
        "template": "item_detail.html",
        "description": "One item's full story — status, components, photos, custody, and its dossier",
        "required_access": None,
        "enabled": True,
        "group": "inventory",
        "steps": [
            {
                "target": ".dtl-header",
                "title": "The Item at a Glance",
                "description": (
                    "Name, category, and status chips up top. When a component "
                    'is installed in a unit, an "Installed in" line appears '
                    "here linking to its parent."
                ),
                "position": "bottom",
            },
            {
                "target": "#components-card",
                "title": "Components",
                "description": (
                    "Unit items — edge boxes, cloud boxes, C2C cameras, "
                    "computers — carry a components card showing what's "
                    "installed inside. Editors can install and remove "
                    "components from here."
                ),
                "position": "top",
                # Renders only for unit categories.
                "optional": True,
            },
            {
                "target": "#component-history-card",
                "title": "Component History",
                "description": (
                    "Every install and removal, in both directions: parts "
                    "that went into this item, and — for components — the "
                    "units this item has been inside."
                ),
                "position": "top",
                "optional": True,
            },
            {
                "target": "#photos-card",
                "title": "Unit Photos",
                "description": (
                    "Photos travel with the item — IN badges for arrival "
                    "condition, OUT for how it left. They're captured at "
                    "receiving, shipping, and deployment, and editors can add "
                    "more here any time."
                ),
                "position": "top",
                "optional": True,
            },
            {
                "target": "#checkout-history-card",
                "title": "Custody",
                "description": (
                    "Who has had this item and when it came back. A "
                    '"currently checked out" chip appears while it\'s in '
                    "someone's hands."
                ),
                "position": "top",
                "optional": True,
            },
            {
                "target": '#photos-card a[href$="dossier.pdf"]',
                "title": "The Dossier",
                "description": (
                    "Export this item's full record — details, history, and "
                    "photos — as a single PDF. Order pages have a matching "
                    '"Export All Unit Dossiers" that zips one per unit.'
                ),
                "position": "top",
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Pilots Due Back (provisioning view)
    # ------------------------------------------------------------------
    {
        "id": "pilots_due_back_tour",
        "name": "Pilots Due Back",
        "page_pattern": "/fulfillment/pilots-due-back",
        "template": "pilots_due_back.html",
        "description": "Loaner units in the field — what's out, what's overdue, and marking returns",
        "required_access": "has_provisioning_view",
        "enabled": True,
        "group": "operations",
        "steps": [
            {
                "target": ".pilots-header",
                "title": "What Lands Here",
                "description": (
                    "Every pilot, try-and-buy, and demo order with units still "
                    "in the field. An order drops off this page automatically "
                    "once everything is back."
                ),
                "position": "bottom",
            },
            {
                "target": ".pilots-header__counts",
                "title": "Reading the Colors",
                "description": (
                    "Red means overdue — the expected return date has passed. "
                    "Amber means due within a week. Everything else is simply "
                    "on loan. The same tints mark each order's status chip "
                    "below."
                ),
                "position": "bottom",
            },
            {
                "target": ".pilots-list",
                "title": "Exactly What's Still Out",
                "description": (
                    "Each card lists the serials still in the field. When a "
                    "unit physically comes back through Receiving, mark it "
                    "returned here so the loan record closes."
                ),
                "position": "top",
                # Absent when nothing is out (empty state instead).
                "optional": True,
            },
            {
                "target": ".pilots-btn--all",
                "title": "Everything Came Back",
                "description": (
                    "Mark All Returned closes out a whole order at once — "
                    "you'll get a confirm first. The order disappears from "
                    "this page the moment nothing is left outstanding."
                ),
                "position": "left",
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Fulfillment Board (provisioning view) — replaces orders_tour, whose
    # key is retired (superseded def kept disabled above for the record).
    # Includes the OEM reconciliation segment approved for "procurement":
    # the PO cards with linked receiving events live HERE, not on
    # /admin/procurement, so the three approved steps land here.
    # ------------------------------------------------------------------
    {
        "id": "fulfillment_board_tour",
        "name": "Fulfillment Board",
        "page_pattern": "/fulfillment",
        "template": "fulfillment.html",
        "description": "Orders in flight — build pipeline, shipping, deployments, and the OEM PO board",
        "required_access": "has_provisioning_view",
        "enabled": True,
        "group": "fulfillment",
        "steps": [
            {
                "target": "#bld-tabs",
                "title": "The Build Pipeline",
                "description": (
                    "Orders roll up into three lanes — Queued, In Progress, "
                    "and Ready for Handoff. Click a lane to see just those "
                    "cards; device-linked cards carry a five-dot build tracker."
                ),
                "position": "bottom",
            },
            {
                "target": "#kanban-ih .fl-ocard:not(.o-hidden)",
                "title": "An Order Card",
                "description": (
                    "Each card is one order: customer, what they're getting, "
                    "and how far the build has come. Orders you're not "
                    "cleared to see simply don't appear on this board."
                ),
                "position": "right",
                "optional": True,
            },
            {
                "target": "#tab-ship",
                "wait_for": "#ap.open",
                "wait_prompt": (
                    "Open any order's panel — click <strong>Assign / Ship</strong> "
                    "on a card — to continue, or skip this step."
                ),
                "title": "The Ship Pane",
                "description": (
                    "Shipping lives in this panel tab: carrier and tracking, "
                    "or a direct transfer. Editors can attach outbound photos "
                    "here — they follow each unit onto its item page and into "
                    "its dossier."
                ),
                "position": "left",
                "optional": True,
            },
            {
                "target": ".deploy-section .fl-btn",
                "title": "Scheduling a Deployment",
                "description": (
                    "The three-step wizard books a deployment: pick the "
                    "order, the units, and the site. Deployed units appear "
                    "on the live map automatically."
                ),
                "position": "top",
                # Manage-gated: absent for view-only users.
                "optional": True,
            },
            {
                "title": "Sensitive Orders",
                "description": (
                    "Some orders are marked sensitive. Without sensitive "
                    "access they're not masked — they're absent entirely, "
                    "here and in exports. With access, their cards carry a "
                    "Sensitive chip."
                ),
                "center": True,
                "optional": True,
            },
            {
                "target": 'button[onclick="exportFulfillment()"]',
                "title": "Getting Data Out",
                "description": (
                    "Export downloads this board as a spreadsheet. Per-unit "
                    "photo dossiers export from each order's detail page — "
                    "open one via the panel header link."
                ),
                "position": "bottom",
                "optional": True,
            },
            # ── OEM reconciliation segment (approved copy, relocated) ──
            {
                "target": "#kanban-oem",
                "wait_for": "#kanban-oem",
                "wait_prompt": (
                    "Switch to the OEM board — click <strong>OEM</strong> at "
                    "the top — to continue, or skip this step."
                ),
                "title": "Linked Receiving Events",
                "description": (
                    "OEM purchase-order cards show what Receiving has logged "
                    'against them — "Received: event #12 (8/10)" — read-'
                    "only, straight from the receiving floor."
                ),
                "position": "top",
                "optional": True,
            },
            {
                "target": "#kanban-oem .oem-card",
                "title": "Counts That Keep Themselves",
                "description": (
                    "The received/ordered count on each card updates as units "
                    "are intaken against the PO, and the card's status "
                    "advances Ordered → Partial → Received on its own."
                ),
                "position": "right",
                # Only when OEM POs exist.
                "optional": True,
            },
            {
                "title": "Reconciliation Never Fights You",
                "description": (
                    "Reconciliation supplements the board — manual edits "
                    "still win. Fix a quantity or status by hand any time; "
                    "receiving events never overwrite what you set."
                ),
                "center": True,
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Order Detail (provisioning view) — replaces order_detail_tour,
    # whose key is retired (superseded def kept disabled above).
    # Wildcard pattern: launcher shows an "open any order first" hint.
    # ------------------------------------------------------------------
    {
        "id": "order_page_tour",
        "name": "Order Detail",
        "page_pattern": "/orders/*",
        "template": "order_detail.html",
        "description": "One order's full picture — status, SKU lines, linked units, photos, and dossier export",
        "required_access": "has_provisioning_view",
        "enabled": True,
        "group": "fulfillment",
        "steps": [
            {
                "target": "#status-badge",
                "title": "Where This Order Stands",
                "description": (
                    "The status walks New → Sourcing → Building → Testing → "
                    "Shipped → Delivered → Installed. Editors update it from "
                    "the buttons beside it."
                ),
                "position": "bottom",
            },
            {
                "target": "#sku-add-btn",
                "title": "SKU Lines",
                "description": (
                    "What the order is for: each line is a model, a quantity, "
                    "and where it's sourced from. These lines drive matching "
                    "against OEM purchase orders."
                ),
                "position": "left",
                # Manage-gated button; viewers see the lines but not the editor.
                "optional": True,
            },
            {
                "target": "#prov-section",
                "title": "Linked Units",
                "description": (
                    "The actual units assigned to this order, each linking to "
                    "its provisioning record. Assignment happens on the "
                    "Fulfillment board."
                ),
                "position": "top",
            },
            {
                "target": "#unit-photos-section",
                "title": "Photos, In and Out",
                "description": (
                    "Every photo tagged to this order's units, grouped by "
                    "direction — how things arrived and how they shipped."
                ),
                "position": "top",
            },
            {
                "target": 'a[href$="dossiers.zip"]',
                "title": "Export All Unit Dossiers",
                "description": (
                    "One click builds a PDF dossier per unit — details, "
                    "history, photos — and hands you the zip. Handy when a "
                    "customer wants the paper trail."
                ),
                "position": "left",
            },
        ],
    },

    {
        "id": "decommissioned_tour",
        "name": "Decommissioned Items",
        "page_pattern": "/inventory/decommissioned",
        "template": "decommissioned.html",
        "description": "Where retired items live, and how to bring one back",
        "required_access": None,
        "enabled": True,
        "group": "inventory",
        "steps": [
            {
                "target": "#dec-header",
                "title": "Retired, Not Deleted",
                "description": (
                    "Items here are out of service but never erased: the row, "
                    "its history, and its audit trail all survive."
                ),
                "position": "bottom",
            },
            {
                "target": "#dec-table",
                "title": "Why, When, and Who",
                "description": (
                    "Every decommissioned item shows the reason, the "
                    "effective date, and who retired it."
                ),
                "position": "top",
            },
            {
                "target": ".dec-reactivate-btn",
                "title": "Bring One Back",
                "description": (
                    "Reactivate returns an item to Pending so it can be "
                    "re-triaged. A reason is required, and both directions "
                    "are recorded in the audit log."
                ),
                "position": "left",
                "optional": True,
            },
        ],
    },

]


def get_tours_for_page(page_path: str) -> list[dict]:
    """Return all tours whose page_pattern matches the given path.

    Patterns are matched exactly unless they contain wildcards (* or ?).
    Use '/provisioning/*' to match sub-pages like '/provisioning/5'.
    """
    result = []
    clean = page_path.rstrip("/")
    for tour in TOURS:
        if not tour.get("enabled", True):
            continue
        pattern = tour["page_pattern"].rstrip("/")
        if clean == pattern or fnmatch.fnmatch(clean, pattern):
            result.append(tour)
    return result


def get_tour_by_id(tour_id: str) -> Optional[dict]:
    """Return a specific tour by its ID."""
    for tour in TOURS:
        if tour["id"] == tour_id:
            return tour
    return None


# Page routes registered WITH a trailing slash. Their slash-less form relies on
# Starlette redirect_slashes, whose absolute Location drops the proxy root path
# and port (GET /assettracker/warranty -> 307 http://localhost/warranty/), so
# launcher navigation must always link the real URL.
_SLASH_PAGES = {
    "/warranty", "/sites", "/trials", "/disposal", "/inventory", "/triage",
    "/map", "/fulfillment",
}


def _page_url(pattern: str) -> str:
    """Navigable URL for a tour's page pattern (wildcards have none)."""
    return pattern + "/" if pattern in _SLASH_PAGES else pattern


def get_all_tours() -> list[dict]:
    """Return summary of all available tours (for help menu)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "page_pattern": t["page_pattern"],
            "page_url": _page_url(t["page_pattern"]),
            "description": t["description"],
            "step_count": len(t["steps"]),
            "required_access": t.get("required_access"),
            "enabled": t.get("enabled", True),
            "group": t.get("group", ""),
        }
        for t in TOURS if t.get("enabled", True)
    ]


def _resolve_tour_template(tour):
    """Resolve the page template name for a tour.

    Priority: explicit tour['template'], else derive from page_pattern
    (strip leading slash, last path segment + '.html'), else None.
    '/inventory' -> 'inventory.html', '/receive' -> 'receive.html'.
    """
    explicit = tour.get("template")
    if explicit:
        return explicit
    pattern = tour.get("page_pattern")
    if pattern:
        seg = pattern.strip("/").split("/")[-1]
        if seg:
            return seg + ".html"
    return None


def _collect_included_partials(template_path, templates_dir, seen=None):
    """Recursively collect {% include "..." %} partial paths (relative to templates_dir).

    Returns a set. Uses `seen` to guard against circular includes.
    """
    import re
    from pathlib import Path
    if seen is None:
        seen = set()
    full = Path(templates_dir) / template_path
    if not full.is_file():
        return seen
    try:
        text = full.read_text(errors="ignore")
    except Exception:
        return seen
    for inc in re.findall(r"{%\s*include\s+[\"']([^\"']+)[\"']", text):
        if inc not in seen:
            seen.add(inc)
            _collect_included_partials(inc, templates_dir, seen)
    return seen


def _build_scoped_corpus(tour, templates_dir, static_js_dir):
    """Build a page-scoped search corpus for one tour.

    Corpus = page template + base.html + transitively included partials
    + all static/js/*.js. CSS is intentionally excluded.

    Returns (corpus_string, None) on success, or (None, reason) when no
    scoped corpus can be built (caller falls back to corpus-wide).
    """
    from pathlib import Path
    tmpl = _resolve_tour_template(tour)
    if not tmpl:
        return (None, "no page_pattern or template; will fall back to corpus-wide")
    page = Path(templates_dir) / tmpl
    if not page.is_file():
        return (None, f"resolved template '{tmpl}' not found; add explicit 'template:' field to this tour")

    parts = [page.read_text(errors="ignore")]

    base = Path(templates_dir) / "base.html"
    if base.is_file():
        parts.append(base.read_text(errors="ignore"))

    partials = set()
    _collect_included_partials(tmpl, templates_dir, partials)
    _collect_included_partials("base.html", templates_dir, partials)
    for p in partials:
        pf = Path(templates_dir) / p
        if pf.is_file():
            try:
                parts.append(pf.read_text(errors="ignore"))
            except Exception:
                pass

    js_dir = Path(static_js_dir)
    if js_dir.exists():
        for f in js_dir.rglob("*.js"):
            if ".bak." in f.name:
                continue
            try:
                parts.append(f.read_text(errors="ignore"))
            except Exception:
                pass

    return ("\n".join(parts), None)


def lint_tour_selectors(tour_id=None):
    """
    Check that every tour-step target selector exists on the tour's own page.

    Page-scoped: each tour's selectors are checked against a corpus built from
    its page template + base.html + transitively included partials + all
    static/js/*.js. Falls back to a corpus-wide scan for a tour only when no
    template can be resolved (no page_pattern/template, or resolved file
    missing) -- reported as a warning.

    Skips:
      - centered steps (center=True): no target
      - steps with lint_skip=True (require a non-empty lint_skip_reason)
      - steps with deferred=True (require a non-empty deferred_reason;
        documented stale selectors awaiting a future rewrite track)
      - pure tag selectors (nav, body): no token to grep

    Returns:
      0 if clean, 1 if rot detected, 2 if validation errors.
    """
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent
    repo_root = app_dir.parent
    templates_dir = app_dir / "templates"
    static_js_dir = repo_root / "static" / "js"
    static_css_dir = repo_root / "static" / "css"

    def extract_tokens(selector):
        ids = re.findall(r"#([\w-]+)", selector)
        classes = re.findall(r"\.([\w-]+)", selector)
        attrs = re.findall(r'\[[^\]]*"([^"]+)"\]', selector)
        return ids + classes + attrs

    _fallback = {}
    def fallback_corpus():
        if "c" not in _fallback:
            parts = []
            for d, exts in ((templates_dir, {".html"}),
                            (static_js_dir, {".js"}),
                            (static_css_dir, {".css"})):
                if not d.exists():
                    continue
                for f in d.rglob("*"):
                    if f.is_file() and f.suffix in exts and ".bak." not in f.name:
                        try:
                            parts.append(f.read_text(errors="ignore"))
                        except Exception:
                            pass
            _fallback["c"] = "\n".join(parts)
        return _fallback["c"]

    tours_to_check = [t for t in TOURS if tour_id is None or t["id"] == tour_id]
    if tour_id is not None and not tours_to_check:
        print(f"No tour with id={tour_id!r} found.")
        return 2

    found_count = 0
    missing = []            # (tid, idx, field, selector, token)
    skipped_generic = []    # (tid, idx, field, selector)
    skipped_lint = []       # (tid, idx, reason)
    skipped_deferred = []   # (tid, idx, reason)
    validation_errors = []  # str
    steps_checked = 0
    per_tour = []           # (tid, scope_label, found_n, missing_n)

    for tour in tours_to_check:
        tid = tour["id"]
        corpus, reason = _build_scoped_corpus(tour, templates_dir, static_js_dir)
        if corpus is None:
            scope_label = f"corpus-wide fallback: {reason}"
            active_corpus = fallback_corpus()
        else:
            scope_label = _resolve_tour_template(tour)
            active_corpus = corpus

        t_found = 0
        t_missing = 0
        for idx, step in enumerate(tour.get("steps", []), start=1):
            steps_checked += 1
            if step.get("center"):
                continue
            if step.get("lint_skip") is True and step.get("deferred") is True:
                validation_errors.append(
                    f"Tour '{tid}' step {idx}: lint_skip=True and deferred=True are mutually exclusive"
                )
                continue
            if step.get("lint_skip") is True:
                r = step.get("lint_skip_reason")
                if not isinstance(r, str) or not r.strip():
                    validation_errors.append(
                        f"Tour '{tid}' step {idx}: lint_skip=True requires non-empty lint_skip_reason string"
                    )
                else:
                    skipped_lint.append((tid, idx, r))
                continue
            if step.get("deferred") is True:
                r = step.get("deferred_reason")
                if not isinstance(r, str) or not r.strip():
                    validation_errors.append(
                        f"Tour '{tid}' step {idx}: deferred=True requires non-empty deferred_reason string"
                    )
                else:
                    skipped_deferred.append((tid, idx, r))
                continue
            for field in ("target", "wait_for"):
                selector = step.get(field)
                if not selector:
                    continue
                tokens = extract_tokens(selector)
                if not tokens:
                    skipped_generic.append((tid, idx, field, selector))
                    continue
                for tok in tokens:
                    if tok in active_corpus:
                        found_count += 1
                        t_found += 1
                    else:
                        missing.append((tid, idx, field, selector, tok))
                        t_missing += 1
        per_tour.append((tid, scope_label, t_found, t_missing))

    # ---- Report ----
    print("Tour selector lint report (page-scoped)")
    print("=" * 40)
    print(f"Tours scanned: {len(tours_to_check)}  |  Steps checked: {steps_checked}")

    if validation_errors:
        print("\n!!! VALIDATION ERRORS (CRITICAL) -- must fix !!!")
        for e in validation_errors:
            print(f"  X  {e}")

    print(f"\n>>> Skipped (lint_skip): {len(skipped_lint)} steps <<<")
    for tid, idx, r in skipped_lint:
        print(f"  - {tid} step {idx}: {r}")

    print(f"\n>>> Deferred: {len(skipped_deferred)} steps <<<")
    for tid, idx, r in skipped_deferred:
        print(f"  - {tid} step {idx}: {r}")

    print("\nPer-tour results:")
    for tid, scope_label, t_found, t_missing in per_tour:
        flag = "" if t_missing == 0 else f"   <-- {t_missing} MISSING"
        print(f"  {tid}  [{scope_label}]  found={t_found} missing={t_missing}{flag}")

    if missing:
        print("\nMissing tokens:")
        for tid, idx, fld, sel, tok in missing:
            print(f"  - {tid} step {idx} {fld}: {sel!r} -> token {tok!r} NOT FOUND")

    # Pure-tag selectors are skipped silently: count only, no per-item noise.
    if skipped_generic:
        print(f"\nSkipped (generic tag selectors, silent): {len(skipped_generic)}")

    print("\nSummary:")
    print(f"  found={found_count}  missing={len(missing)}  "
          f"skipped_lint={len(skipped_lint)}  skipped_deferred={len(skipped_deferred)}  "
          f"skipped_generic={len(skipped_generic)}  validation_errors={len(validation_errors)}")
    if validation_errors:
        print("  RESULT: VALIDATION ERRORS -- fix lint_skip_reason(s)/deferred_reason(s).")
        return 2
    elif missing:
        print("  RESULT: ROT DETECTED.")
        return 1
    else:
        print("  RESULT: clean.")
        return 0
