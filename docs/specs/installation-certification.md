# Installation Certification — schema and model spec

Status: **APPROVED.** Design ratified; not yet built. This is the reference the
I-slices are built against. Source artifacts:
`docs/mockups/superdesign/installation_completion.html` (UI intent) and the
Appliance Post-Install Checklist PDF (the real verification document).

## What this feature is

> Lineage: an earlier `install_certification` table (migration 050) encoded an
> in-app checklist design for this feature. It was never wired up and is
> superseded by this spec; retired in migration 054.


When a device is installed at a customer site, the installer (internal SE or a
partner such as NTX Integrators) produces a **Appliance Post-Install Checklist PDF** —
customer info, system info, network speed test, notes, and installation photos in
one document. The tracker does not re-capture any of that. It:

1. Receives the completed post-install PDF against the deployment record.
2. Records who certified it (internal user) and who installed it (installer name).
3. Marks the installation certified — flips the deployment to `complete`.

No in-app verification checklist, no site-detail form, no installer login. The PDF
is the sign-off.

## Relationship to the other cert flows (all distinct)

| | Build Certification (SHIPPED) | Installation Certification (this doc) | Cloud2 cam certs (undesigned) |
|---|---|---|---|
| When | Build stage | Installation complete at site | Separate lighter process |
| Grain | Per device (OEM serial) | Per deployment record | Per cam |
| Verification | In-app, two-person, all-pass | In the uploaded PDF | TBD |
| In-app capture | QA + SMART + components + files | PDF + installer name + certify | TBD |
| Gate | All checks pass, both halves | PDF present | TBD |

## Where it attaches

`DeploymentRecord` pipeline `scheduled -> in_transit -> on_site -> installing ->
complete` (+ `cancelled`). The cert is the **`installing -> complete`**
transition. The existing `/fulfillment/deployments` board already renders this
pipeline, so this is an action added to existing `installing` cards, not a new
page.

## Ratified decisions

- **Dedicated table, single inline PDF on the row.** One
  `installation_certification` table. The one required PDF is stored as columns on
  the cert row (photos are already embedded in it), not a separate child table. It
  serves inline via the `Content-Disposition: inline` + `target="_blank"` pattern
  shipped alongside the component-rows slice.
- **One internal certifier + recorded installer name.** `certified_by` = the
  internal user who certifies. `installer_name` / `installer_company` = free text
  entered from the PDF (e.g. "Taylor" / "NTX Integrators"). A field engineer or Casey uploads the
  SE-supplied document; the installer is recorded, not an app user. No special
  permission mapping beyond provisioning manage.
- **PDF required to certify.** No PDF, no certification.
- **One cert per deployment record.** A re-install is a new deployment record,
  which arrives through the normal order / PO flow. Redeploy is **out of scope**
  for this feature. There is no in-row history or `reason` field — each deployment
  record has at most one installation cert.
- **Role gating.** Read: provisioning viewer. Write/certify: provisioning manage.
- **No in-app checklist.** The gate is "PDF present"; verification lives in the
  PDF.

## Certification lifecycle
deployment reaches installing

internal user opens Certify Installation on the deployment card

row created (status = pending)

user uploads the post-install PDF (required)

user enters installer name / company, optional notes, completion date

user clicks Complete & Certify Installation

gate: PDF attached?

yes -> status = certified, certified_by set, certified_at stamped

-> DeploymentRecord.status = complete, installed_date stamped

no  -> rejected ("a post-install PDF is required to certify")

## Schema — `installation_certification` (new table, migration 053)

| column | type | role |
|---|---|---|
| id | int PK | |
| deployment_record_id | int FK -> deployment_record, CASCADE, not null, unique | one cert per record |
| status | varchar(16) not null, default 'pending' | `pending \| certified` |
| installer_name | varchar(128) null | from the PDF, e.g. "Taylor" |
| installer_company | varchar(128) null | from the PDF, e.g. "NTX Integrators" |
| notes | text null | optional internal notes |
| completion_date | date null | install date from the PDF |
| pdf_original_name | varchar(256) null | display name |
| pdf_stored_name | varchar(256) null | uuid + ext on disk |
| pdf_content_type | varchar(128) null | for inline serve |
| pdf_size_bytes | int null | raw bytes (matches build_certification_files) |
| certified_by | varchar(128) null | internal certifier display_name |
| certified_at | datetime null | server timestamp at certify |
| created_at | datetime not null | |
| created_by | varchar(128) null | who opened the row |

Indexes: unique `(deployment_record_id)`, `(status)`.

PDF stored under a new `INSTALL_CERT_UPLOAD_DIR`,
`<dir>/<deployment_record_id>/<uuid>.pdf`.

## Routes

| method + path | gate | purpose |
|---|---|---|
| GET `/fulfillment/deployments` (exists) | viewer | mark certified cards; add certify entry point |
| POST `/fulfillment/deployments/{id}/install/upload` | manage | upload the post-install PDF |
| POST `/fulfillment/deployments/{id}/install/certify` | manage | certify (PDF-required gate), flip status |
| GET `/fulfillment/install-cert/{cert_id}/pdf` | viewer | serve the PDF inline (new tab) |

## UI (translate mockup intent into dark tokens)

`installation_completion.html` is light-mode intent only — translate to the dark
emerald-on-slate tokens in `docs/mockups/README.md`:

- **Deployment board (existing)**: `installing` cards get a **Certify
  Installation** action; `complete` cards show certified state (certified-by,
  installer, finalized date, a "Post-Install PDF" inline link).
- **Certify Installation modal**: a PDF drop zone (required), installer
  name/company inputs, optional notes, completion date, and the **Complete &
  Certify Installation** button. No checklist, no site-detail grid.

## Slice plan

- **I1** — migration 053 (`installation_certification` table + indexes,
  `INSTALL_CERT_UPLOAD_DIR`) and read-only board changes: certified `complete`
  cards render their cert state. No write path yet.
- **I2** — Certify Installation modal + write path: PDF upload (required-gate),
  installer name/company + notes capture, certify, the `installing -> complete`
  transition + `installed_date` stamp, and inline PDF serve reusing the
  `Content-Disposition: inline` + `target="_blank"` pattern.
- **I3** — completed-installations polish: locked completed cards, the inline PDF
  link, certified-by + installer, finalized date.

Not in scope: in-app checklist, site-detail form, files child table, composite
report PDF (the uploaded PDF is the certificate), redeploy / re-install flow.
