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
                "title": "How to Read It",
                "description": "The hero strip at the top shows your top-line counts: total items plus how many are deployed, ready to deploy, or pending. Below that, status panels break the totals down by device category, and the recent activity feed shows what changed lately.",
                "center": True,
                "optional": True,
            },
            {
                "title": "Taking Action",
                "description": "The dashboard doesn't edit anything itself. Use Quick Actions for the most common operations (add an item, check in/out, triage), or jump to the Inventory page to manage devices in detail. The search bar at the top accepts a keyboard shortcut — press / from anywhere to jump.",
                "center": True,
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
        "enabled": False,
        "group": "inventory",
        "required_access": None,
        "steps": [
            {
                "target": "#global-search-input",
                "title": "Search Input",
                "description": (
                    "Type any keyword to search across all 16 device categories "
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
        "description": "Review and approve discovered network devices",
        "required_access": "is_editor_or_above",
        "enabled": False,
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
                    "Each row shows a discovered device with its MAC address, "
                    "IP, hostname, manufacturer, and which inventory category "
                    "was suggested by the OUI database."
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
                "target": ".btn-success",
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
        "enabled": False,
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
        "enabled": False,
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
                "target": ".btn-primary",
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
        "enabled": False,
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
        "enabled": False,
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
    {
        "id": "receive_tour",
        "name": "Receive & Scan",
        "page_pattern": "/receive",
        "description": "Walk through the multi-step device intake workflow",
        "required_access": "has_receiving_access",
        "enabled": False,
        "group": "operations",
        "steps": [
            {
                "target": "#mode-receive-btn",
                "title": "Receiving Mode",
                "description": (
                    "This page has two modes. <strong>Receive New Device</strong> "
                    "walks you through intake of new equipment. Toggle to "
                    "<strong>Assign Drive</strong> for NAS drive bay assignment."
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
                    "Events group multiple devices from the same delivery together "
                    "for tracking and audit purposes."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#step-scan",
                "title": "Step 2: Scan Barcode",
                "description": (
                    "Use your camera to scan the device barcode or QR code. "
                    "If scanning isn't available, enter the serial number manually. "
                    "The system checks for duplicates automatically."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": "#quick-mode-cb",
                "title": "Quick Mode",
                "description": (
                    "Enable <strong>Quick Mode</strong> to scan multiple devices rapidly. "
                    "When on, recognized barcodes are auto-submitted to inventory — "
                    "the camera stays open and a counter tracks your scans. "
                    "Duplicates show a red toast; unknown serials fall back to the "
                    "manual form. Great for bulk receiving."
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
                    "Optionally take a photo of the device label. The system "
                    "uses OCR to extract serial numbers and model info "
                    "from the image, auto-filling fields where possible."
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
        "enabled": False,
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
        "enabled": False,
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
    # Procurement Analytics (financial access)
    # ------------------------------------------------------------------
    {
        "id": "procurement_tour",
        "name": "Procurement Analytics",
        "page_pattern": "/admin/procurement",
        "template": "admin_procurement.html",
        "description": "High-level spend analysis, vendor performance scores, and purchase history",
        "required_access": "has_financial_access",
        "enabled": False,
        "group": "procurement",
        "steps": [
            {
                "target": ".cards",
                "title": "Spend Summary",
                "description": (
                    "Four headline numbers: total tracked spend, number of active "
                    "vendors, year-to-date cost, and average unit cost across "
                    "all purchases. These drive the tables below."
                ),
                "position": "bottom",
                "highlight_padding": 6,
                "optional": True,
            },
            {
                "target": ".table-section",
                "title": "Cost by Vendor & Category",
                "description": (
                    "Ranked tables showing which vendors and categories account "
                    "for the most spend. Click any vendor name to open their "
                    "full profile with device-level drill-down."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".table-section",
                "title": "Vendor Performance",
                "description": (
                    "Quality scores (0–100) auto-calculated from warranty claim "
                    "rates and trial outcomes. Color-coded bars make it easy "
                    "to spot underperforming vendors at a glance."
                ),
                "position": "top",
                "highlight_padding": 4,
                "optional": True,
            },
            {
                "target": ".table-section",
                "title": "Recent Purchases",
                "description": (
                    "The most recent procurement records across all categories. "
                    "Each row shows device, vendor, cost, procurement method "
                    "(direct, rental, donation, etc.), and PO number. "
                    "Use the Excel/CSV export buttons to pull this for reporting."
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
                    "Inside the user drawer, 15 permission toggles are organized into groups: "
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
                    "Add credentials to the <code>.env</code> file on the NUC."
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
        "enabled": False,
        "group": "admin",
        "steps": [
            {
                "target": "#connection-status",
                "title": "Connection Status",
                "description": (
                    "Shows whether the Zendesk subdomain, email, and API token "
                    "are configured and working. Click <strong>Test Connection</strong> "
                    "to verify live connectivity. Credentials live in "
                    "<code>.env</code> on the NUC."
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
        "enabled": False,
        "group": "admin",
        "steps": [
            {
                "target": "#file-input",
                "title": "Upload Excel File",
                "description": (
                    "Choose the master inventory Excel file (.xlsx). "
                    "The file is parsed across all 17 sheets — no changes are "
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
        "description": "Hardware manufacturer registry used by the network scanner to identify and categorize discovered devices",
        "required_access": "is_editor_or_above",
        "enabled": False,
        "group": "admin",
        "steps": [
            {
                "target": ".summary-cards",
                "title": "OUI Reference Overview",
                "description": (
                    "Three summary numbers: total registered manufacturers, "
                    "total OUI prefixes tracked, and how many inventory devices "
                    "were matched to an OUI. The network scanner uses this "
                    "database to identify discovered devices by MAC address."
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
                    "Discovered devices matching these prefixes are auto-categorized "
                    "in the review queue."
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
                    "on the Main QA/Hardware Server in the lab. "
                    "Nothing is stored in the cloud — the app runs entirely on-site. "
                    "The database file is on the server's SSD, separate from the app code."
                ),
                "optional": True,
            },
            {
                "center": True,
                "title": "How Is It Backed Up?",
                "description": (
                    "A Backup QA/Hardware Server runs as a warm standby. "
                    "Every night at 2 AM, a full database snapshot and all app code "
                    "are synced to the Backup QA/Hardware Server automatically. "
                    "If the primary server goes down, the backup can take over in about 15 minutes."
                ),
                "optional": True,
            },
            {
                "center": True,
                "title": "How Does Data Get In?",
                "description": (
                    "Data enters the system three ways: "
                    "<strong>(1) Manually</strong> — team members add or edit devices directly in the app. "
                    "<strong>(2) Network Scanner</strong> — the scanner discovers devices on the lab network and queues them for review. "
                    "<strong>(3) Spreadsheet Import</strong> — an Excel master inventory file can be uploaded under Admin → Spreadsheet Sync to bulk-load or update records."
                ),
                "optional": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # Concept: How does network discovery work?
    # ------------------------------------------------------------------
    {
        "id": "concept_network_scanner_tour",
        "name": "How Does Network Discovery Work?",
        "page_pattern": "/dashboard",
        "description": "Explains how the network scanner finds devices and gets them into inventory",
        "required_access": "is_editor_or_above",
        "enabled": True,
        "group": "onboarding",
        "steps": [
            {
                "center": True,
                "title": "Step 1 — The Scanner",
                "description": (
                    "A network scanner runs on the NUC and sweeps the lab network "
                    "using <strong>nmap</strong> (roughly every 5 minutes). "
                    "It identifies active devices by IP address and MAC address. "
                    "The NUC is connected to two networks: "
                    "office WiFi and the Hardware/QA lab via ethernet."
                ),
                "optional": True,
            },
            {
                "center": True,
                "title": "Step 2 — OUI Matching",
                "description": (
                    "Each MAC address has a 3-byte prefix called an OUI that identifies "
                    "the hardware manufacturer (e.g. <code>AABBCC</code> = Axis Communications). "
                    "The app looks up the OUI in its reference database (Admin → OUI Reference) "
                    "to auto-categorize the device — for example, an Axis MAC becomes a "
                    "<strong>Camera</strong> candidate."
                ),
                "optional": True,
            },
            {
                "center": True,
                "title": "Step 3 — Review Queue",
                "description": (
                    "Discovered devices land in the <strong>Review Queue</strong> "
                    "(Admin → Review Queue). An editor or admin reviews each entry: "
                    "confirm the category, fill in serial number and location, and approve. "
                    "Approved devices are added to the main inventory. "
                    "Dismissed entries are removed from the queue without being added."
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
                    "Each department card shows a heatmap of its 14 permission defaults — green "
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
        "enabled": False,
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


def get_all_tours() -> list[dict]:
    """Return summary of all available tours (for help menu)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "page_pattern": t["page_pattern"],
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
    '/inventory' -> 'inventory.html', '/admin/users' -> 'users.html'.
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
