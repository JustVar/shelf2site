# Credential Rotations Runbook

Operational procedures for rotating credentials in the asset_tracker system.

Scope: this runbook covers credential rotations that are **operational, not
emergency**. For known compromises (active leak, suspected unauthorized access),
treat as incident response and rotate immediately regardless of the cadence
guidance below.

## Cadence guidance

| Credential | Cadence | Trigger |
|---|---|---|
| Postgres `asset_tracker_user` (apphost DB) | Pre-go-live, then ~quarterly | Before LAN-wide go-live; routine hygiene afterward |
| Application user accounts (admin-triggered) | ~6 months | Routine hygiene, or on suspected compromise |

## What is NOT in this runbook

- Camera / access-control device passwords. Devices live on a segregated VLAN
  behind a firewall; not rotated as part of routine hygiene.
- Other secrets in `.env` (SESSION_SECRET_KEY, SCANNER_API_KEY, NOCODB_API_TOKEN,
  CREDENTIAL_ENCRYPTION_KEY, ZENDESK_API_TOKEN, SLACK_WEBHOOK_URL,
  SLACK_ADMIN_WEBHOOK_URL). Each has its own rotation considerations and is not
  covered here.

---

## 1. Postgres `asset_tracker_user`

The asset_tracker DB's superuser. Lives in the `db` container on apphost.
Stored in `.env` at two keys: `POSTGRES_PASSWORD` and embedded in
`DATABASE_URL`.

### Authoritative live state

The runtime authority is the role's password inside Postgres itself
(`pg_authid.rolpassword`). The `.env` entries make the running app and future
container re-init use the matching value.

### Procedure

1. Choose a new password. Generate something strong:

       openssl rand -base64 24

   Save it to a temporary scratch buffer (not a file). You'll paste it in
   three places below.

2. Change the password live in Postgres:

       docker compose exec db psql -U asset_tracker_user -d asset_tracker \
           -c "ALTER USER asset_tracker_user WITH PASSWORD '<new-password>';"

   Expected output: `ALTER ROLE`. The change takes effect immediately for
   *new* connections; existing connections stay authenticated until they
   close.

3. Update `.env` in two places — both should reflect the new password:

       # POSTGRES_PASSWORD line
       POSTGRES_PASSWORD=<new-password>

       # DATABASE_URL line (password embedded in the URL)
       DATABASE_URL=postgresql://asset_tracker_user:<new-password>@db:5432/asset_tracker

   Use `sed` carefully or edit by hand. Verify both lines are updated before
   restarting:

       grep -E "^(POSTGRES_PASSWORD|DATABASE_URL)" .env

4. Restart the app container to pick up the new `DATABASE_URL`:

       docker compose restart app

   The `db` container does NOT need restarting — the new password is already
   live in Postgres from step 2.

5. Verify the app reconnected:

       docker compose logs --tail=30 app 2>&1 | grep -iE "error|database|connection" | tail -10

   No connection errors expected. Visit the app at
   https://192.0.2.10:8443/assettracker/ — login flow and a data-loaded page (e.g.
   /inventory) should both work.

### Expected downtime

A brief window (seconds to a couple of minutes) between the `ALTER USER` and
`docker compose restart app`. Existing app workers will use the old cached
password until they're cycled. Schedule outside business hours if user impact
matters.

### Rollback

If verification fails:

1. Revert `.env` to the old password (you should have kept a backup of the
   line before editing).
2. Run `ALTER USER asset_tracker_user WITH PASSWORD '<old-password>';` again.
3. `docker compose restart app`.

If you no longer have the old password: it's recoverable only from your
scratch buffer or a `.env` backup. There's no Postgres-side recovery —
hashed passwords aren't reversible.

---

## 2. Application user passwords (admin-triggered)

For rotating user passwords inside the app (e.g., the admin user's own
password, or another user's password on suspected compromise).

### Cadence

- Routine: every ~6 months.
- On-demand: any time a user account is suspected compromised, or when an
  employee departs.

### Mechanism

The app currently supports admin-triggered **forced password change** but
not a direct "admin sets a new password for user X" workflow. The flow is:

1. Admin flips `must_change_password = True` on the target user via
   `PATCH /api/admin/users/{user_id}` (UI exposes this on `/admin/users`).
2. User attempts to log in. They're redirected to `/change-password` and
   forced to set a new password before they can proceed.
3. User chooses their own new password and logs in normally.

For the admin's own password: admin goes to `/change-password` directly
(self-service flow).

### Procedure (rotating someone else's password)

1. Notify the user. See the communication template below.

2. As admin, navigate to `/admin/users`, find the target user.

3. Flip the must_change_password flag. The UI control should be on the
   user-edit row (refer to the admin_users.html implementation for the
   current label). API equivalent if needed:

       PATCH /api/admin/users/{user_id}
       Body: {"must_change_password": true}

4. Send the user the prepared notification (template below).

5. The user logs in with their existing password, is redirected to
   `/change-password`, sets a new one, and proceeds.

### Procedure (rotating your own admin password)

1. Log in as admin.
2. Navigate to `/change-password` (link in sidebar).
3. Enter old password, new password, confirm.
4. Submit. You stay logged in with the new password.

### Known limitation: existing sessions persist

When an admin flips `must_change_password = True`, the user's currently-active
session is **not invalidated**. They can continue using the app under their
existing session cookie until it expires naturally, despite the flag being
set. The flag only triggers on next login.

Implication: if rotation is triggered by suspected compromise of an active
session, this flow does NOT terminate the compromised session. As a
workaround:

- Use the user-lock endpoint (`POST /api/admin/users/{user_id}/lock`) first
  to prevent any further activity, then set `must_change_password = True`,
  then unlock when the user is ready to reset.
- Or shorten the session lifetime in the app config (separate change, not
  part of routine rotation).

A "force logout on password change" feature is a future code track and not
implemented as of this runbook's writing.

### Communication template

Send to the affected user (email, Slack, or in-person) before flipping the
flag. Adjust tone for the relationship.

> **Subject: Password reset required — asset_tracker**
>
> Hi <name>,
>
> As part of our routine security cycle [or: due to <specific reason>], your
> asset_tracker password needs to be reset. The next time you log in to
> https://192.0.2.10:8443/assettracker/, you'll be prompted to choose a new
> password.
>
> Your existing password will work one more time — it'll just take you
> straight to the change-password screen. After that, use your new password
> normally.
>
> Let me know if you run into any issues.
>
> Thanks,
> <admin>

---

## Verification checklist (post-rotation)

After any rotation, confirm the system is healthy:

- [ ] Login works (admin and a sample non-admin user)
- [ ] A data-loaded page renders (e.g., /inventory, /dashboard)
- [ ] No connection or auth errors in app logs:

          docker compose logs --tail=50 app 2>&1 | grep -iE "error|traceback" | tail -10

- [ ] If the rotation was credential-related, confirm the old credential no
      longer works (try a manual `psql` connection with the old password —
      expect auth failure).
