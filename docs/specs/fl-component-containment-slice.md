# Slice: component containment + history (Option A)

Decisions locked 2026-07-10: OPTION A — the deployed `component_history` event log is the source of truth (installed/uninstalled/moved), current state derived; parent-eligible units = edge_box, cloud_box, camera_c2c, computer; status enum gains `Installed` only. H7 (Assign Drive removal) lands INSIDE this slice.

## Data layer

1. Migration (next per directory; CLAUDE.md's counter is stale again — directory is truth): add `Installed` to the status enum; anything component_history itself needs per the investigation (the panel's missing counterpart display may be query-side only — discovery decides).
2. `current_containment` view: latest event per component; NULL/uninstalled = standalone. This is THE read path — no other surface derives containment its own way.
3. Invariant guards in the write routes (the known Option A risk): cannot install an already-installed component (must uninstall/move); cannot uninstall a non-installed one; parent must be a parent-eligible category and a real item; no cycles (a parent cannot be installed into its own containment chain); a unit-category item cannot be installed as a component (revisit if a real need appears).
4. Legacy backfill: migrate the 31 `device_components` rows into component_history installed events (the already-planned path), with row-count assertions and provenance noted.

## Behavior

5. Write routes: install (component -> parent, optional slot_label), uninstall, move (atomic uninstall+install). Install sets status `Installed`; uninstall prompts for/returns to a standalone status (default In Storage). Editor-gated.
6. Place inheritance: an Installed component's effective place = its parent's place, derived at read time through the view. Inventory, search, item detail, exports, and the map data path show the inherited place; the location select on an Installed item is disabled with "location follows its parent unit" hint. The place/status triage check extends: Installed component with a divergent stored place is a data-check finding, not a render error.

## UI

7. Item Detail — units: a "Components" card listing current contents (name, category chip, serial mono, slot, installed date) with Install Component picker (search by serial/name, filtered to non-unit, non-installed items) and per-row Remove/Move actions. fl language: tint buttons, one confirm modal.
8. Item Detail — components: containment line in the header area ("Installed in <unit> since <date>" linking to the parent, or "Standalone"); Component History panel finally renders real events BOTH directions with the counterpart named and linked.
9. Scan-intake hook: after a component category is received via scan, offer "Assign into a unit?" follow-up (unit picker, same install route) — the modern replacement for the Assign Drive workflow.
10. H7: remove the Assign Drive tab/mode from Receive, delete the dead router file, update the receive tour copy. (Mounting is impossible anyway; this is pure removal.)

## Contracts

Item Detail existing sections, triage roles/checks, map + inventory place displays (inheritance must not break kiosk/visibility filtering — inherited place composes with the visibility helper), scan-intake flow from the correctness group, `nas_drives` API (leave as-is; its bays are NOT migrated into this model in this slice — note for a future unification decision).

## Gates

Invariant tests (each guard positive + negative); e2e round trip: receive component -> assign into unit -> verify Installed status + inherited place on item detail, inventory, search, and map -> move to second unit -> verify history shows both residencies with counterparts -> uninstall -> standalone again. Backfill row counts. H7 removal smoke (Receive shows single mode, no console errors, tour updated). Both themes. Contract suite green. Four-location sync.
