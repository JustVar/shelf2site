# Local time

    STATUS:   RATIFIED 2026-09-24 by Jus
    Written:  2026-09-24
    Board:    BACKLOG-TRIAGE.md item 42 (replaces N11)
    Taken at: HEAD 16197f8, branch main
    Scope:    Every place the app shows, exports or records a date or a
              time. Storage of timestamps does not change.
    Anchors:  Every file:line below is at 16197f8 and ages from the first
              commit that touches the file. Re-read before editing.

## Why

The database and the app container both run in UTC (READ 2026-09-24:
`SHOW timezone` is Etc/UTC; container `TZ` unset, `time.tzname` is UTC).
No page converts a time, so every timestamp shows UTC with no label.
Separately, "today" is computed on the same UTC clock, so from 7 pm CDT
(6 pm CST) on, anything dated "today" is recorded as tomorrow. No existing
spec covers time (docs grep, 2026-09-24).

## Rulings (Jus, 2026-09-24)

1. **Display.** Every moment in time is shown in America/Chicago, with
   daylight saving handled. Existing "UTC" labels change.
2. **Today.** "Today" means today's date in Central, and that fix is part
   of this item: Python, browser date inputs and database defaults.
   Rows already stored are not rewritten.
3. **Files follow the screen.** CSV and XLSX exports, PDF text and export
   filenames use the same rule as the pages.
4. **Label.** Every time shown carries the real abbreviation, CDT or CST
   (`%Z` on an aware value). A date alone carries no label.
5. **Zone data is pinned.** `tzdata` goes into `requirements.txt` in
   slice A, so a slimmer base image cannot break conversion.
6. **One zone for everyone.** Every user works on Central time, as of
   2026-09-24. Per-user zones stay out of scope.

## Rules the build follows

- **Storage stays UTC.** Naive `timestamp` columns keep holding UTC wall
  time; `func.now()` and `utcnow()` defaults are untouched. Conversion
  happens only on the way out.
- **A naive datetime from the database is UTC.** The helper attaches UTC
  and converts. An aware one (the 4 timestamptz columns) converts as is.
- **A `date` is a calendar day and is never converted.** 37 of the 62
  template `strftime` calls format `Date` columns and need no change.
- **A name is not a type.** `created_at`, `last_updated` and
  `received_date` are `Date` on some models and `DateTime` on others. Each
  site is classed by the model it reads, never by the field name.

## The helper: `app/localtime.py` (new)

- `APP_TZ`: `ZoneInfo("America/Chicago")`. Zone data comes from the
  image's `/usr/share/zoneinfo` today (READ: loads; the `tzdata` pip
  package is not installed). Ruling 5 pins `tzdata`.
- `to_local(dt)`: None stays None; a `date` that is not a `datetime` is
  returned unchanged; naive means UTC.
- `fmt_local(dt, fmt)`: `to_local` then `strftime`. Callers put `%Z` in
  the format wherever a time is shown (ruling 4).
- `local_now()`: aware datetime in `APP_TZ`.
- `local_today()`: `local_now().date()`.
- `parse_utc(text)`: ISO text to naive UTC; an offset converts, no
  offset is UTC, a bare date or bad text is None. Added in slice B.
- `fmt_stamp(text, fmt)`: `parse_utc` then `fmt_local`, for times stored
  as text (provisioning stage stamps).
- `register(env)`: adds the Jinja filters `localtime` and `localstamp`
  (and nothing else) to a template environment.

**29 separate `Jinja2Templates` instances** exist, one in `main.py` and
one per route module (READ). A filter registered in one is invisible to
the others, so each module calls `register(templates.env)` once, next to
its existing `base_path` global. A structural test enforces it.

## Where it applies (census v1, READ at 16197f8)

**Pages, a moment in time (25 template calls).** 6 already labelled UTC
(`build_cert_history.html:74,76,78`, `c2c_history.html:97,100,103`); 14
show a time with no label; 5 show only the date of a timestamp, so the
day itself is wrong after 7 pm. Full list in the census file. Every one
moves to `|localtime(fmt)`.

**Pages, strings built in Python and printed raw or sliced.**
`provisioning.py:157` and `:171`, `lifecycle.py:67-68`, the provisioning
stage stamp written at `provisioning.py:729` and sliced at
`provisioning.html:248` and `provisioning_detail.html:289`,
`admin_maintenance.html:40` (`announced_at[11:16]` plus a UTC label),
the JS error modal at `admin_errors.html:181`, and
`admin-zendesk.js:38`, and `fulfillment.py:1652, 1654, 1684, 1722`
(`isoformat(sep=" ", timespec="minutes")` strings printed raw at
`certification_detail.html:200, 289, 321`).

**Files.** `provisioning.py:1310` and `fulfillment.py:1230` (export
columns), `dossier.py:63,178` (PDF), `fulfillment.py:2065, 2074` (build cert
PDF, `_build_cert_report_pdf`), `c2c.py:885` (cert text),
`maintenance_routes.py:103` (backup status label), and export filenames:
5 naive `datetime.now()` (`provisioning.py:1315`, `warranty.py:386`,
`triage.py:688`, `bulk.py:233`, `inventory.py:458`).

**Today, Python.** 37 `date.today()` calls in 14 files, all to
`local_today()`. Includes the 4 filename uses.

**Today, browser.** Three date inputs default to `new Date().toISOString()`,
which is the UTC date: `site_detail.html:314`, `item_detail.html:886`,
`warranty.html:665`. They take the browser's own date instead.

**Today, database.** The live catalog has **16** `date` columns with a
UTC default (READ 2026-09-24): 15 are `CURRENT_DATE`, and
`public.device_assignments.assigned_date` is `now()`. 13 of them are
declared in the models (`models.py:981, 1984, 1985, 2034, 2035, 2050,
2068, 2094, 2097, 2111, 2114, 2128, 2133`). 3 have no model:
`item_schema.intake_photos.created_at`, `item_schema.location_types.created_at`,
and the legacy `public.maintenance_log.maintenance_date`. (The
`IntakePhoto` model is `public.intake_photos`, a different table.)
`Item.last_updated` also has `onupdate=func.current_date()`, which runs
in the UTC database session. Migration 079 sets all 16 defaults to
`(now() AT TIME ZONE 'America/Chicago')::date`; the 13 models and the
`onupdate` match. Defaults only; no row changes.

**Out of the display path, left alone.** The 5 aware
`datetime.now(timezone.utc)` calls (arithmetic); `audit.py:80` value
snapshots (stored data); `admin-maintenance.js:169`
`toLocaleTimeString()` (already the browser's zone); JSON APIs that no
page renders.

## Slice B corrections (READ at 9d948f2)

- `lifecycle.py:69-70` feed a JSON API no page or script fetches. Out of
  the display path; left alone.
- `maintenance_routes.py:105` (backup `ts_label`) is shown on a page. It
  moved from Files into slice B.
- `fulfillment.py:1656` and the close and cancel JSON (`:2234`, `:2254`)
  are not shown anywhere. Left alone.
- Stage stamps stay stored as UTC ISO text and show through `localstamp`.
- The error detail modal reads a new `created_at_display` field; the
  API keeps `created_at`.
- The Zendesk org date converts in the browser to the Central date.

## Slice C notes (READ at 96e3e66)

- The structural test bans `date.today()` under `app/`. Slice D adds
  naive `datetime.now()` when it fixes the 5 export filenames.
- The `Item.last_updated` onupdate uses the same SQL as the new
  default, `(now() AT TIME ZONE 'America/Chicago')::date`.
- `scripts/route_census.py` is converted. The two legacy import
  scripts, `scripts/link_custom_builds.py` and
  `scripts/import_all_categories.py`, write data and cannot be
  verified; they are left alone and recorded on the board.
- The three browser date inputs use `toLocaleDateString('en-CA')`,
  the browser's own date as YYYY-MM-DD.

## Slice D notes (READ at eba357f)

- Export columns show the Central date of a timestamp, with no label.
- PDF and certificate times carry CDT or CST.
- Export filenames keep their format and use the Central clock.
- The structural tests now also ban a naive `datetime.now()` under
  `app/`, and a UTC label in any string under `app/`.
- `lifecycle.py:69-70` and `fulfillment.py:1656` stay out: no page or
  file shows them.

## Slices

- **A. Helper and wiring.** `app/localtime.py`, `register` in all 29
  modules, tests. No visible change.
- **B. Pages.** Every page site above. Browser-gated.
- **C. Today.** `local_today()` everywhere, the three date inputs,
  migration 079 and the model defaults. Schema change (defaults only).
- **D. Files.** Export columns, PDF text, cert text, filenames.

B and D may merge if the diff stays small. C stands alone because it
carries a migration.

## Gates

- **Behaviour test, able to fail.** `fmt_local` across both DST edges
  and the evening case: 2026-03-08 07:59 UTC is 01:59 CST;
  08:00 UTC is 03:00 CDT; 2026-11-01 06:59 UTC is 01:59 CDT and
  07:00 UTC is 01:00 CST; 2026-09-25 00:30 UTC is 2026-09-24 19:30 CDT.
  A UTC passthrough fails every conversion case.
- **Structural tests.** No template calls `.strftime(` on a `DateTime`
  value outside the filter; no `date.today()` or naive `datetime.now()`
  under `app/`; every module that builds `Jinja2Templates` calls
  `register`. Each proven able to fail on the pre-slice tree.
- **Browser.** A gate record stamped at a known UTC time shows the
  Central time and label on its page; a page that shows a `Date` column
  is unchanged. Console clean.
- **Suite total predicted before every run.**

## Open reads

- **An inbound time: no data at risk.** `provisioning.py:1095-1116`
  stores the `timestamp` from an uploaded validate.py report
  straight into the naive UTC column `validation_date`. No report has ever
  been uploaded (READ 2026-09-24: `/data/validation-reports` does not
  exist in the app container; 0 `device_provisioning` rows have a
  `validation_date` or a report path). The generator is outside this
  repo and its timestamp format is UNREAD. Slice B makes the parse
  explicit: an offset converts to UTC before storing; no offset is
  stored as UTC, as today. Revisit when the first real report exists.
- **Census method gap, closed.** The first sweep grepped `isoformat()`
  and missed calls with arguments; 6 display sites in `fulfillment.py`
  were found only on the second pass (now listed above).
- Board correction: the DB has 152 naive and 4 aware timestamp columns,
  all in base tables (READ 2026-09-24). The board's 80 and
  "delete_requests only" are wrong, as is `SCHEMA_REFERENCE.md:49`
  ("error_log.created_at, only instance"). The fourth aware column is
  `item_schema.csv_import_map.imported_at`.

## Out of scope

Per-user time zones. Rewriting stored dates. Changing the DB or container
zone (it would shift every naive `now()` default and mix two clocks in
one column).
