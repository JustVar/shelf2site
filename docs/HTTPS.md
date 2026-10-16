# HTTPS on apphost — server/ops runbook

This is the **operator** guide: what was set up, where the keys live, how it's
wired, and how to renew. For the **end-user** "install the certificate on your
laptop/phone" instructions, see [CA_CERT_DISTRIBUTION.md](CA_CERT_DISTRIBUTION.md).

> **Why HTTPS at all?** Phones and desktops only expose the camera
> (`getUserMedia`) and let the app install as a PWA (service worker) when the
> page is a **secure context** — i.e. served over HTTPS. Plain HTTP blocks both.
> This setup makes the app a secure context so the barcode scanner and photo
> capture work on real devices.

## The short version

| Thing | Value |
|---|---|
| App over HTTPS | `https://192.0.2.10:8443/assettracker/` |
| Legacy HTTP | `http://192.0.2.10:8100/assettracker/` → **301 redirect** to the HTTPS URL |
| Port 80 | bare `http://192.0.2.10/` also redirects into the app over HTTPS |
| Why 8443, not 443 | 443 is already held by the Docker **registry** container (its own TLS). We don't move it; the app rides 8443. |
| CA (trust root) | `mkcert root@apphost`, valid **2026-07-12 → 2036-07-12** |
| Leaf cert (what nginx serves) | SANs `192.0.2.10`, `apphost`, `localhost`, `127.0.0.1`; valid **2026-07-12 → 2028-10-12** |
| TLS terminates at | host **nginx** (`:8443 ssl`), proxies to the app container on `127.0.0.1:8081` |

## Where the files live (all OUTSIDE the repo)

Everything TLS lives under **`/etc/ssl/asset-tracker/`** on apphost (root-owned):

| File | What it is | Sensitivity |
|---|---|---|
| `rootCA.pem` | the CA certificate (public) | public — safe to hand out |
| `rootCA-key.pem` | the CA **private key** | **secret** — `chmod 600`, never leaves the box |
| `asset-tracker.crt` | the leaf cert nginx serves | public |
| `asset-tracker.key` | the leaf **private key** | secret — `chmod 600` |
| `Shelf2Site-LAN-CA.crt` | a copy of `rootCA.pem` renamed for distribution | public — this is the file end users install |

The CA is also copied to `/usr/local/share/ca-certificates/shelf2site-lan-ca.crt` and
registered with `update-ca-certificates` so the server itself trusts it (server-side
`curl` health checks work without `-k`).

`mkcert`'s `CAROOT` for this box is `/etc/ssl/asset-tracker` — pass it explicitly
(`CAROOT=/etc/ssl/asset-tracker mkcert ...`) so a fresh cert is signed by the same CA.

> **Not the same as the registry CA.** The Docker registry on :443 terminates its
> own TLS with a *different*, unrelated self-signed CA (`legacyCA` in docker
> volume `repo-docker_certs`). Two separate trust concerns — don't cross them.
> There is also a stale **old-NUC** mkcert CA (`mkcert` CA from the old NUC)
> that may still be trusted on some laptops; it is unrelated to this box.

## How it's wired (nginx — config is server-side, not in the repo)

Live file: `/etc/nginx/sites-available/asset-tracker` (symlinked into `sites-enabled/`).
Backups from the cutover are beside it (`*.bak.pre-https-*`, `*.bak.stepA`).

Three server blocks:

1. **`listen 8443 ssl http2;`** — the HTTPS front door. Serves the leaf cert,
   TLS 1.2/1.3, and proxies `/assettracker/` to `http://127.0.0.1:8081`. The
   proxy locations are a byte-for-byte mirror of the old `:8100` block, so SSE,
   HTML no-cache, and forwarded headers behave exactly as before. Because this
   block is `ssl`, `$scheme` is `https`, so `X-Forwarded-Proto: https` reaches
   the app — which is what flips on Secure cookies and HSTS.
2. **`listen 8100;`** — legacy HTTP, now a pure `return 301
   https://$host:8443$request_uri;`. `$request_uri` preserves the full
   `/assettracker/...` path and query, so every existing bookmark still lands
   exactly where it did (this is the trailing-slash lesson applied to redirects).
3. **port 80 default** (`sites-available/default`) — bare `/` jumps to
   `/assettracker/`; anything already under a path is preserved verbatim (no
   `/assettracker` prepend, so no doubled prefix).

`nginx` here is 1.24.0, so HTTP/2 is enabled via `listen ... ssl http2` (the
standalone `http2 on;` directive is 1.25.1+).

### SSE note
`/assettracker/events/stream` is a long-lived response. `sse-starlette` sends
`X-Accel-Buffering: no`, which nginx honors to disable buffering for that
response, and the app sends a keepalive comment every ~30 s (under the 60 s
`proxy_read_timeout`). No dedicated SSE location is needed — the mirrored proxy
settings are sufficient, and SSE was verified open over TLS.

## App side (this IS in the repo)

`app/main.py` adds `SecureSessionCookieMiddleware`: it promotes the
`inventory_session` cookie to `Secure` **per request, only when the request
arrived over HTTPS** (`scope['scheme'] == 'https'`). We do *not* use a static
`HTTPS_ONLY=true` flag, because the in-container contract suite drives the app
over plain `http://127.0.0.1:8081` and httpx refuses to send a Secure cookie
back over an http origin — a static flag would silently log every test fixture
out. Keep **`HTTPS_ONLY=false`** in the server `.env`.

`APP_BASE_URL` in the server `.env` is set to `https://192.0.2.10:8443/assettracker`
so notification (Slack/email) links point at the HTTPS URL. Changing `.env`
requires `docker compose up -d` (recreate) to take effect, not just `restart`.

HSTS is emitted only when `X-Forwarded-Proto: https` is present (`app/main.py`),
so it turns on automatically behind the HTTPS front door and stays off on any
raw-HTTP path.

## Renewal

- **Leaf cert** expires **2028-10-12**. Regenerate before then:
  ```bash
  sudo bash -c 'export CAROOT=/etc/ssl/asset-tracker; cd /etc/ssl/asset-tracker && \
    mkcert -cert-file asset-tracker.crt -key-file asset-tracker.key \
    192.0.2.10 apphost localhost 127.0.0.1'
  sudo systemctl reload nginx
  ```
  Signed by the same CA, so **end users do not reinstall anything**.
- **CA** expires **2036-07-12**. Only when the CA itself is regenerated must end
  users reinstall `Shelf2Site-LAN-CA.crt` (a new leaf alone does not require it).
- After any regen, verify: `openssl x509 -in asset-tracker.crt -noout -dates -ext subjectAltName`
  and `curl -sI https://192.0.2.10:8443/assettracker/login` (200, no `-k` needed on the box).

## Trust install (per device — the manual step)

Until a device trusts `Shelf2Site-LAN-CA.crt` it shows a warning; the origin is
**still a secure context after clicking through**, so the camera works either
way — the trust install just removes the warning and lets the PWA/service worker
register cleanly. Per-platform steps are in
[CA_CERT_DISTRIBUTION.md](CA_CERT_DISTRIBUTION.md). Installing into a **user Root
store requires interactive consent** (a Windows/OS dialog by design), so it can't
be scripted headlessly — it's a ~2-minute manual step per device.
