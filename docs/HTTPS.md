# Serving Shelf2Site over HTTPS

Run the app behind a reverse proxy that terminates TLS. The app itself speaks
plain HTTP on `127.0.0.1:8081` and never holds a certificate.

> **Why HTTPS at all?** Browsers only allow the camera (`getUserMedia`) and
> installing the app as a PWA (service worker) on a **secure context**, which
> means HTTPS. Over plain HTTP the barcode scanner and photo capture do not
> work on phones.

## 1. Get a certificate

- **The app has a public DNS name:** use a free certificate from Let's
  Encrypt (for example with `certbot --nginx`). Nothing needs installing on
  the devices that use the app.
- **The app is only reachable on a private network:** a public certificate
  authority cannot issue for a private IP, so make a private one with
  [mkcert](https://github.com/FiloSottile/mkcert):

  ```bash
  sudo mkdir -p /etc/ssl/asset-tracker
  sudo bash -c 'export CAROOT=/etc/ssl/asset-tracker; cd /etc/ssl/asset-tracker && \
    mkcert -install && \
    mkcert -cert-file asset-tracker.crt -key-file asset-tracker.key \
      assets.internal 192.0.2.10 localhost 127.0.0.1'
  sudo chmod 600 /etc/ssl/asset-tracker/*-key.pem /etc/ssl/asset-tracker/asset-tracker.key
  ```

  Use your own host name and address in place of `assets.internal` and
  `192.0.2.10`. `rootCA-key.pem` signs every future certificate: keep it
  secret and backed up. `rootCA.pem` is public; that is the file each device
  installs (step 4).

## 2. Put nginx in front

`deploy/nginx/asset-tracker.conf` is a working example: HTTPS on 443, a
redirect from port 80, the app proxied under `/assettracker/`, and static
files served directly. Copy it to `/etc/nginx/sites-available/`, change the
server name and certificate paths, link it into `sites-enabled/`, then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Server-sent events need no special location: the app sends
`X-Accel-Buffering: no` and a keepalive every ~30 seconds, under the 60 second
`proxy_read_timeout`.

## 3. Set the app side

In `.env`:

| Setting | Value | Why |
|---|---|---|
| `ROOT_PATH` | `/assettracker` | Matches the location the proxy mounts the app under. |
| `APP_BASE_URL` | `https://assets.example.com/assettracker` | Links in Slack and email messages. |
| `HTTPS_ONLY` | `false` | Leave it off. The session cookie is marked Secure per request whenever the request arrived over HTTPS (`SecureSessionCookieMiddleware` in `app/main.py`). A fixed flag would also mark it Secure for the contract suite, which talks plain HTTP to `127.0.0.1:8081`, and log every test out. |
| `FORWARDED_ALLOW_IPS` | default `127.0.0.1,172.16.0.0/12` | The proxies whose `X-Forwarded-*` headers the server believes. Add your proxy's address if it is elsewhere. |

HSTS is sent only when the request came through the HTTPS proxy, so it turns on
by itself and stays off on any direct HTTP path. After changing `.env`, run
`docker compose up -d` (a plain `restart` does not reload it).

## 4. Trust a private certificate on each device

Only needed for the mkcert route. Until a device trusts `rootCA.pem` it shows a
warning. The page is still a secure context after clicking through, so the
camera works either way, but installing the root removes the warning and lets
the PWA register cleanly. Rename the file to something recognisable
(`Shelf2Site-LAN-CA.crt`) and hand it out; it is public.

- **Windows:** double-click the file, Install Certificate, Current User,
  "Place all certificates in the following store", Trusted Root Certification
  Authorities.
- **macOS:** open it in Keychain Access, add it to the login keychain, then set
  it to Always Trust.
- **iPhone and iPad:** open the file to download the profile, install it under
  Settings > General > VPN & Device Management, then turn it on under
  Settings > General > About > Certificate Trust Settings.
- **Android:** Settings > Security > Encryption & credentials > Install a
  certificate > CA certificate.

Installing a root needs the user to confirm it on the device, by design, so it
cannot be scripted.

## Renewing

- A Let's Encrypt certificate renews itself through certbot's timer.
- An mkcert leaf lasts a little over two years. Run the same `mkcert` command
  again and reload nginx. It is signed by the same root, so devices do not need
  to reinstall anything. Only a new root means reinstalling on every device.
- After any renewal: `openssl x509 -in asset-tracker.crt -noout -dates -ext subjectAltName`
  and `curl -sI https://assets.example.com/assettracker/login`.
