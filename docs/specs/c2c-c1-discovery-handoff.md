# C2C Camera Cert — C1 Discovery Handoff

## What this session did

Ran C1 discovery for the C2C camera cert track, and shipped the one prerequisite
that discovery uncovered: a `sku_requirements` shape reconciliation that was
blocking nothing on the board today but sat directly on C1's in-scope cam-line
write path.

**C1 build was not started.** Migration 055, the acquisition path, and the
read-only C2C view are still ahead. This session ends with C1 fully grounded and
one small fix-first commit landed.

## Shipped this session

- **`836bb73` -> `718ef44`** — Align fulfillment SKU chips to canonical model
  key. Three chip reads in `fulfillment.html` switched from `.get('sku')` to
  `.get('model')`, plus the lone seed row (id 70 / AT-9001) rewritten from
  `{sku, qty}` to `{model, qty, source}`. Four-way synced, scratch cleared.
  Verified live: the overdue-rail chip renders `4x EDGE-2000`, console clean.

## Grounded facts (read-confirmed, with source)

| Fact | Detail | Where read |
|---|---|---|
| Migration number | `055` is next free | migrations dir (053, 054 taken) |
| Cert table FK target | `device_provisioning.id`, real FK + CASCADE, buildable as spec'd | `models.py` DeviceProvisioning |
| Camera-behind-provisioning | polymorphic `device_table` + `device_id`, **no DB FK** to `cameras.id` | `models.py` DeviceProvisioning |
| `sku_requirements` canonical shape | `{model, qty, source}` | form L307, `_sku_availability` L62 |
| Shape consistency | now aligned across form, availability helper, templates, seed row, spec, L1077 comment | this session |
| Server write path | stores `body["sku_requirements"]` **verbatim**, no reshape | `orders.py` create ~198, update ~249-250 |
| Discriminator decision | SKU-prefix convention (`EDGE-*` vs cam SKU); no `category` field at C1 | grounded on n=1 cam-line data (none exist) |
| Cam-line write | in scope for C1; rides the verbatim-store path above | decision this session |

## Open items to settle before C1 writes code

1. **`stages` content for cam provisioning rows.** The column is
   `nullable=False` with no default; the live edge-box value is a 42-stage list.
   Cams do not ride that pipeline, so they need a minimal list or `[]`. Whether
   `[]` is safe depends on whether any C2C view code iterates `stages` — one
   short read at C1 start resolves it. **Unresolved.**

2. **Spec sync edits** (`docs/specs/c2c-camera-certification.md`):
   - `migration 054` -> `055` (flagged at L82 + L130 — **re-verify the line
     numbers before editing**, they drift).
   - Shape note in the acquisition section, if it still references the old
     framing.
   - **The `models.py` L1077 comment needs NO change** — discovery confirmed it
     already states the correct `{model, qty, source}` shape.

## Recommended C1 entry sequence

1. Spec-sync commit (the edits above) so C1 builds against an accurate spec.
2. Read whether any view iterates `DeviceProvisioning.stages`, then decide the
   minimal cam `stages` value.
3. Migration `055` — `c2c_certification` table + indexes
   (`device_provisioning_id`, `status`).
4. Minimal acquisition path: provision cams (`device_table="cameras"`) to an
   order, plus the in-scope cam-line write through the existing intake form.
5. Read-only C2C view. No certify write path yet (that is C2).

## Carry-forward gotchas relevant to C1/C2

- **JSONB in-place mutation** is not tracked by SQLAlchemy — whole-dict
  reassignment required. Directly relevant to C2 firmware-evidence capture.
- **Polymorphic device lookup**: to reach the camera behind a provisioning row,
  do `TABLE_MODELS[device_table]` then query by `device_id`. The DB will not
  enforce that `device_id` points at a real camera.
- The whole existing fulfillment/cert flow is hardcoded
  `device_table == "edge_boxes"` in ~10 guards. C2C needs its own minimal path,
  not a reuse of those routes.
- SSH-heredoc patch discipline (not Write+scp), guarded scripts with count
  asserts, `.bak` deleted pre-commit, diff review before commit, four-location
  sync per commit, separate `origin` / `company` pushes.

## State at handoff

- HEAD `718ef44`, four-way synced (apphost / workstation / origin / company).
- Tree clean, scratch cleared both sides.
