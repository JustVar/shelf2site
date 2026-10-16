# Fulfillment pipeline direction, OEM and third party paths

Status: DIRECTION, not built. Recorded so it is not lost and so future tracks are
sequenced against it. Nothing here is specced and nothing here changes the
currently specced tracks.

Owner note: this is product direction, not repo fact. When any of it is built,
`CLAUDE.md` becomes the owner of the resulting architecture.

## The model

Two axes, each with an in-house path and an external path.

**Build and certification**

- The in-house team builds and certifies, using the current process: QA and hardware dual
  signoff, all pass gate, composite PDF, board close.
- OEM vendor builds and certifies. They hand over certification results and
  documents. The in-house team receives and files rather than performs.

**Installation**

- An in-house engineer installs at the customer site, and a post install
  certification IS collected.
- A third party installer installs, and a post install certification is most
  likely NOT collected and will NOT be required.

## Decisions already made

**OEM certification is a DIFFERENT RECORD**, not a flag on
`BuildCertification`. There is an OEM tab on the fulfillment page, not yet built,
which will carry OEM processes.

That is the right call. `BuildCertification` carries QA and hardware dual signoff
columns, an all pass gate, and per half 409 guards, all of which are internal
process machinery an OEM certification would not use. Reusing the table would
mean filling those with placeholder values.

**Build ownership is the routing discriminator.** A build is owned by either
in-house personnel or the OEM. Setting the owner to OEM routes that order and its
cards to the OEM tab.

**The OEM artifact is files only, no parsing.** PDFs, documents, images, whatever
the vendor sends, uploaded and attached to the record.
`BuildCertificationFile` is already generic enough to be the model:
`original_name`, `stored_name`, `content_type`, `size_bytes`, `uploaded_by`,
`uploaded_at`. The OEM record needs an equivalent table and nothing more
sophisticated.

That closes an open question early. No extraction of serial, PO, SKU or results
into columns, so no validation layer and no conflict resolution when a vendor
document disagrees with what the system believes about a serial.

**`certified_by` on an OEM certification is the OEM**, not the in-house person who
filed it.

## Cardinality, the hard part

OEMs handle bulk orders, and the certification granularity they provide is not
under in-house control:

- **Preferred: one certification per unit.** Full traceability, matches both
  existing models.
- **Accepted fallback: one certification for a representative unit**, covering
  the whole order, where every unit in the order is the same.

**Neither existing model supports the fallback.** `BuildCertification` hangs off
`device_provisioning_id` and C2C hangs off a per serial provisioning row. Both
are strictly per unit. An order level certification fits neither, so the OEM
record needs a scope concept that the others do not have.

**Validation rule hiding in the qualifier.** An order level certification is only
meaningful when the order is HOMOGENEOUS BY SKU. A representative certificate for
unit A attests nothing about unit B if they are different SKUs. If order level
certifications are allowed, that condition should be enforced rather than
trusted, because a mixed order carrying one certificate would appear covered and
would not be.

**Traceability cost, stated plainly.** Under an order level certificate, the
answer to "what is the certification for unit X" becomes "covered by order level
certificate N" rather than a unit specific document. If a unit fails in the field
and the certificate is the evidence, that is a weaker answer. Worth knowing when
deciding how hard to push vendors for per unit certificates.

## Open when this is built

- **Where does `owner` live?** On the customer order, the provisioning row, or
  the certification record. It drives routing, so it probably belongs upstream of
  the certification, but that is unread and undecided.
- **How is certification scope modelled?** The record has to express both "this
  certifies unit X" and "this certifies every unit in order N". Options include a
  scope column with a nullable unit link, or always linking to the order with an
  optional serial. Whichever is chosen, resolving "the certification covering
  unit X" must work for both cases.
- **Is the homogeneous SKU condition enforced or advisory?** See the validation
  rule above.
- **Does installation certification become conditional in the schema, or in
  process only?** If "our engineer vs third party" drives different required
  documents and approval steps, it wants a typed field rather than being inferred
  from whether `installer_company` happens to be filled in.

**Settled, no longer open:** the OEM artifact is files only, no parsing. See
above.

## Units are not linked to deployment visits

**Serial is the identifier tracked across inventory and deployments. Today it
does not reach deployments.**

Read from the model: only TWO tables carry `deployment_record_id` -
`UnitPhoto` (line 403) and `InstallationCertification` (line 2100).
`DeviceProvisioning`, which holds the units, does NOT.

So the chain is:

```
DeviceProvisioning  -> customer_order_id
DeploymentRecord    -> customer_order_id
```

Units and visits both hang off the order, and nothing connects them to each
other. "Which serials did this install cover" is an INFERENCE through the shared
order, not a recorded fact.

**It resolves correctly today by accident.** Each live order has exactly one
deployment record: 70 to 13, 71 to 14, 72 to 15, each carrying 2 provisioning
rows. But `deployment_records.customer_order_id` is a plain FK with no
uniqueness. Nothing prevents an order from having two visits, a second trip for
the remaining units. The first time that happens, unit to visit attribution
becomes undeterminable from the data.

**Telling asymmetry:** `UnitPhoto` DOES carry `deployment_record_id`. The app
already models "this artifact belongs to this visit" for photographs, and does
not for the units themselves.

### Consequence for installation certification history

Installation certification is structurally different from build certification:

| | Build cert | Installation cert |
|---|---|---|
| Subject | one unit | one site visit |
| Identifier | `oem_serial` column on the row | none, reached via the deployment |
| Cardinality | one row per attempt per unit | one row per attempt per SET of units |

So `/certifications/history/{serial}` answers "what happened to this unit."
The installation equivalent would answer "which site visits included this unit,
and how did each go," which returns visits rather than unit attempts.

**Deployment keyed history is the right primary surface**, and not only for
framing. It is the only one backed by recorded facts. A serial keyed
installation view would display an inferred association, correct today by the
accident of one to one orders and visits, and quietly wrong the first time an
order splits across two trips.

**A serial keyed view should be built only after units are linked to deployments
directly.** Otherwise it inherits an inference it cannot validate.

## Third party install certificates, not required but sometimes present

Confirmed: third party installs will NOT require a post install certification,
but there will be times when one is received.

Installation certification record 13 is already this case. Taylor at NTX Integrators, a
third party install, WITH a certification and a completion date of 2026-06-28.

So the rule is "not required," never "not allowed." Any validation built later
must accept a third party install that carries a certificate, and must not treat
its absence as an error.

## Effect on currently specced tracks

**None.** Both cover the internal path as it exists today.

- `certification-audit-logging.md` draws its event vocabulary from the current
  `BuildCertification` statuses. Since OEM certification will be a different
  record, it will need its own events when built, and those do not overlap.
- `installation-cert-append-only.md` makes the existing table append only. That
  holds regardless of who installs, and is arguably more valuable once third
  party installs are routine.

Neither should be held for this. Ship them for the internal path.

## Sequencing note

The OEM tab is a build, not a patch. When it starts, the `owner` concept lands
first because routing depends on it, and routing touches the fulfillment board
that the C2C and build cert work already share. Read
`docs/mockups/` and the fulfillment specs in `docs/specs/` before designing it,
since the board restyle and delivery pipeline buildout were already mocked up.
