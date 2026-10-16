# Tour System — Development Guide & Lessons Learned

**Shelf2Site internal reference**
Version 1.0 | March 2026

---

## 1. Purpose

This document captures what was learned building and debugging the Inventory Tour. It is the reference for anyone writing, updating, or debugging tours going forward. Do not start a new tour without reading this first.

---

## 2. How the Tour Engine Works

Tours are defined in `app/tours.py` and rendered by `app/static/js/guide.js`.

### 2.1 Key Files

| File | Role |
|---|---|
| `app/tours.py` | All tour definitions — steps, targets, descriptions, groups |
| `app/static/js/guide.js` | Tour engine — overlay, tooltip, positioning, polling |
| `app/static/css/main.css` | Tour overlay and tooltip styles |
| `app/templates/inventory.html` | QV modal, `closeQuickView()` global function |

### 2.2 Step Resolution Flow

When a step runs, `_showStep(stepIndex)` does the following in order:

1. Calls `closeQuickView()` if the step target is NOT `.qv-modal`
2. Checks visibility using `step.wait_for` if defined, otherwise `step.target`
3. If visible: resolves `targetEl` to `step.target` (not `step.wait_for`)
4. Draws the overlay cutout immediately (before scroll)
5. Scrolls target into view
6. After 300ms: re-draws cutout, renders tooltip, positions tooltip
7. Restores `pointerEvents` on overlay

If the target is not visible:
- Has `wait_for` + `wait_prompt` → shows wait prompt (poll mode)
- Has `optional: True` → skips in the current navigation direction
- Otherwise → retries up to 5 times with backoff

### 2.3 wait_for vs target — Critical Distinction

This is the most important thing to understand about the engine.

| Field | Purpose |
|---|---|
| `wait_for` | Selector used to detect when the element is ready (visibility check) |
| `target` | Selector used for the cutout highlight and tooltip positioning |

**They can and should be different.** For example:
- `wait_for: "#qv-overlay"` — wait until the QV overlay is open
- `target: ".qv-modal"` — but highlight and position the tooltip on the modal card itself

If you use `wait_for` and `target` pointing to the same element, fine. But if the element you want to highlight is a child of the gating element, always split them.

**Why this matters:** The engine resolves `targetEl` to `step.target`, not `step.wait_for`. If you only set `wait_for` and omit `target`, the engine falls back correctly. But if `wait_for` points to a full-screen overlay and `target` points to the card inside it, the cutout and tooltip will anchor to the card — which is what you want.

---

## 3. Z-Index Stack

The full z-index stack as of v1.0. Do not add new elements in this range without updating this table.

| Layer | Selector / Element | z-index |
|---|---|---|
| Tour overlay | `.tour-overlay` | 1100 |
| Highlight target | `.tour-highlight-target` | 1150 |
| QV overlay (inventory) | `#qv-overlay` | 1160 |
| Tour tooltip | `.tour-tooltip` | 1200 |
| Toast notifications | `.toast` | 1300 |

**Rule:** Any modal or panel that a tour step needs to highlight must sit above the tour overlay (1100) but below the tooltip (1200). If a modal is added in the future and a tour step needs to highlight it, check its z-index first.

---

## 4. Tour Step Fields Reference

```python
{
    "target": "#css-selector",         # Required. Element to highlight and anchor tooltip.
    "title": "Step Title",             # Required. Shown in tooltip header.
    "description": "Step text...",     # Required. HTML allowed.
    "position": "bottom",              # Optional. bottom (default), top, left, right.
    "highlight_padding": 8,            # Optional. Pixels of padding around the cutout.
    "wait_for": "#another-selector",   # Optional. Wait for this element before showing step.
    "wait_prompt": "Instruction...",   # Optional (requires wait_for). Text shown while waiting.
    "optional": True,                  # Optional. If target not found, skip silently.
    "required_access": "is_editor_or_above",  # Optional. Access level required to see step.
}
```

---

## 5. Tour Definition Fields Reference

```python
{
    "id": "my_tour",                   # Required. Unique identifier. Used for reset/tracking.
    "name": "My Tour",                 # Required. Display name in help modal.
    "description": "...",              # Required. Shown in help modal.
    "page_pattern": "/inventory",      # Required. URL path this tour applies to.
    "group": "inventory",              # Required. Group slug for help modal categorization.
    "enabled": True,                   # Required. False = hidden from all users.
    "required_access": None,           # Optional. None = all users. String = access check.
    "steps": [...]                     # Required. List of step dicts.
}
```

**Groups currently in use:**

| Slug | Used for |
|---|---|
| `inventory` | Dashboard, search, triage |
| `operations` | Warranty, sites, disposal, receive |
| `fulfillment` | Provisioning, orders |
| `procurement` | Trials, vendor, procurement |
| `admin` | Admin pages, audit log, team management |
| `onboarding` | Concept/explainer tours |

---

## 6. Lessons Learned — Inventory Tour

These are the bugs that were hit, what caused them, and how they were fixed. Read before writing a new tour.

---

### 6.1 Overlay Covers Fixed Elements Before Cutout Draws

**Symptom:** The bulk action bar appeared when a checkbox was clicked, then disappeared when the tour tooltip rendered.

**Root cause:** `_showStep` ran `scrollIntoView` and then waited 300ms before drawing the cutout. During that 300ms the full overlay covered the page, hiding fixed elements.

**Fix:** Call `_updateOverlay(targetEl)` once immediately before `scrollIntoView` to draw the cutout right away, then re-draw it inside the 300ms timeout after scroll settles.

**Takeaway:** Any step targeting a `position: fixed` element is at risk of this. Always test steps with fixed elements and watch for flicker.

---

### 6.2 wait_for and target Resolving to Wrong Element

**Symptom:** Quick View step tooltip snapped to the top-left corner of the screen (0,0 position).

**Root cause:** When `wait_for` and `target` are different selectors, the engine was setting `targetEl` to the `wait_for` element (e.g. `#qv-overlay`, a full-screen div). The cutout covered the entire viewport and the tooltip had no valid anchor.

**Fix:** After the visibility check, resolve `targetEl` to `document.querySelector(step.target)` instead of keeping the `wait_for` element.

**Takeaway:** Always check that `target` and `wait_for` are set correctly when they point to different elements. The rule is: `wait_for` = gating signal, `target` = what to highlight.

---

### 6.3 closeQuickView Closing the Modal Before Positioning

**Symptom:** Quick View step showed wait prompt correctly, user clicked a row, QV opened, tour tried to position — but the tooltip snapped to 0,0 again.

**Root cause:** `closeQuickView()` was added to the start of every `_showStep` call to clean up QV when navigating away. But it also ran at the start of the QV step itself, closing the modal before the cutout could be drawn against it.

**Fix:** Guard the call — only run `closeQuickView()` when `step.target !== '.qv-modal'`.

**Takeaway:** Any step that targets a modal or panel that also needs to be open for positioning — make sure cleanup calls are guarded by step target.

---

### 6.4 modal-closed Event Repositioning to Wrong Location

**Symptom:** After opening the edit modal from QV and canceling, the tour tooltip snapped to top-center, partially off screen.

**Root cause:** The `modal-closed` event listener was running `_resizeHandler`, which checks `step.target` width directly. When the edit modal closed, QV was also closed, so `.qv-modal` had no dimensions. The handler tried to reposition anyway and fell back to a bad position.

**Fix:** Replace the `modal-closed` handler with a dedicated handler that calls `_showStep(this.currentStep)` instead. This runs the full visibility check — if QV is closed, it shows the wait prompt again.

**Takeaway:** Use `_showStep` for event-driven re-entry, not inline repositioning. The full check handles all cases correctly.

---

### 6.5 QV Overlay Z-Index Conflict with Tour Overlay

**Symptom:** Even after fixing positioning, the tour overlay was drawing on top of `#qv-overlay` because both were at z-index 1100.

**Fix:** Bumped `#qv-overlay` to z-index 1160 (above tour overlay at 1100 and highlight at 1150, below tooltip at 1200).

**Takeaway:** Before writing a step that targets something inside a modal, check the modal's z-index against the tour stack. If it's at or below 1100, bump it into the 1101–1199 range.

---

### 6.6 Tooltip Clipping at Top of Viewport

**Symptom:** Device Table step tooltip was clipped at the top of the screen when `position: "top"` was set and the table was near the top of the viewport.

**Fix:** Changed position to `"bottom"` for `#table-content`.

**Takeaway:** `"top"` only works if there is enough room above the element. For elements that are always near the top of the page (tables, filter bars, header sections), use `"bottom"`. The flip logic in the engine helps but is not a substitute for choosing the right position to begin with.

---

### 6.7 Wrong Tour Step Modified

**Symptom:** During a position fix, the `dashboard_tour`'s `#table-content` step was accidentally changed instead of the `inventory_tour`'s.

**Root cause:** Both tours have a `#table-content` step. The search matched the first one in the file.

**Fix:** Reverted `dashboard_tour` to `"top"` and applied `"bottom"` to the correct `inventory_tour` step.

**Takeaway:** When modifying steps, always specify the tour name and approximate line number. Confirm the surrounding context (tour id, step title) before saving. Multiple tours share the same target selectors.

---

### 6.8 Step Order Affects Tour Exit Behavior

**Symptom:** The tour ended silently after the Device Table step when the Quick View step came before the Bulk Actions step. Bulk Actions was optional and not visible, so it skipped — but it was the last step, so the tour exited instead of showing Quick View.

**Fix:** Moved Bulk Actions before Quick View so that skipping it still left Quick View as the final step.

**Takeaway:** Optional steps should never be last. Always end a tour on a step that is guaranteed to be visible. When designing step order, think about what happens if optional steps are skipped.

---

## 7. Rules for Writing New Tours

1. **Test every wait_prompt step manually** — click through the full interaction the user is expected to perform. If the UI changes state during the wait (modals open, QV loads), check what the tour does when that state changes.

2. **Never end a tour on an optional step.** The last step must always be visible on the target page.

3. **Use `"bottom"` for elements near the top of the viewport.** Only use `"top"` when there is clearly enough room above the element.

4. **Check z-index before targeting anything inside a modal.** If the modal is at or below 1100, it will conflict with the tour overlay.

5. **Split `wait_for` and `target` when the visible signal and the highlight target are different elements.** Never use a full-screen overlay as a `target`.

6. **Keep `closeQuickView` guard in mind.** If a future tour step targets a different modal that also needs to be open for positioning, add a similar guard. The pattern is: `if (typeof closeSomething === 'function' && step.target !== '.modal-selector') closeSomething();`

7. **Specify tour name and line number when modifying steps in Claude Code.** Both tours that share a selector is a real risk.

8. **Set all 26 existing tours to `enabled: False` unless actively ready for users.** New tours start disabled and are enabled when tested and approved.

9. **After any guide.js change, run the full tour end to end** — forward through all steps, back through all steps, skip from the middle, and close via the X button. All four paths must work.

---

## 8. Testing Checklist for New Tours

Before enabling a tour for users, run through this checklist:

- [ ] Forward: all steps render correctly in sequence
- [ ] Back: navigating backward closes any open modals and repositions correctly
- [ ] Skip: skip from the middle ends the tour cleanly
- [ ] X button: closes tour without errors
- [ ] Wait prompts: user interaction triggers step continuation correctly
- [ ] Optional steps: if target is missing, step skips silently in the correct direction
- [ ] Tour ends with completion toast on the final step
- [ ] No z-index conflicts with modals targeted by the tour
- [ ] Tooltip does not clip outside the viewport on any step
- [ ] Tour is enabled only for the correct access level (`required_access`)

---

## 9. Current Tour Status

| Tour ID | Page | Group | Enabled | Notes |
|---|---|---|---|---|
| `inventory_tour` | `/inventory` | inventory | Yes | 8 steps, all users |
| `asset_triage_tour` | `/triage` | inventory | Yes | 8 steps, editors and above |
| All others (26 tours) | Various | Various | No | Defined but not yet enabled |

---

> Update this document after any changes to guide.js, tours.py, or the z-index stack. Version 2.0 should be written after the Triage tour is tested and enabled.
