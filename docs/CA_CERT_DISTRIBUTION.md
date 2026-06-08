# LAN Certificate — Installation Guide

> **Note:** HTTPS is not yet enabled on apphost — the app currently
> serves over HTTP at http://192.0.2.10:8100/assettracker/. This guide
> applies once HTTPS (LAN CA) is set up; the https:// URLs below are
> the intended endpoints for that future state.

## Message to send to team members

---

**Subject: One-time setup required — Asset Tracker**

Hi team,

To access the Hardware Asset Tracker and install it as an app on your device, you need to install a security certificate. This is a one-time 2-minute step.

**What it is:** A private certificate that tells your browser "this internal Company server is trusted." Without it, your browser will show a security warning when you visit the site. It only applies to the company's internal server — it has no effect on any other website you visit.

**Why it's needed:** The app runs on HTTPS (encrypted), which is required for it to be installable as an app on your desktop or phone. The certificate is what makes that encryption work.

**The URL after setup:** `https://192.0.2.10/assettracker/`

---

## Installation steps

### Windows — Chrome

1. Download the certificate file: **LAN-CA.crt** *(shared via Teams/email)*
2. Double-click the file — the Certificate Import Wizard opens

   **Screen: "Welcome to the Certificate Import Wizard"**
   - Click **Next**

   **Screen: "File to Import"**
   - The filename is already filled in — click **Next**

   **Screen: "Certificate Store"**
   - Select **"Place all certificates in the following store"** *(do NOT use Automatically)*
   - Click **Browse**
   - In the list, select **Trusted Root Certification Authorities**
   - Click **OK** — you'll see it appear in the Certificate store field
   - Click **Next**

   **Screen: "Completing the Certificate Import Wizard"**
   - Confirm it says **Trusted Root Certification Authorities** in the summary
   - Click **Finish**

   **Security Warning popup: "Do you want to install this certificate?"**
   - Click **Yes**

   **"The import was successful"** — click OK

3. **Fully quit Chrome** — close ALL Chrome windows, then check the system tray (bottom-right corner) for a Chrome icon and right-click → Exit. Chrome must be completely closed, not just the tab.
4. Reopen Chrome and go to `https://192.0.2.10/assettracker/` — you should see a **lock icon (🔒)** to the left of the address bar and no warning page. Chrome no longer shows a green padlock — the gray lock icon means the connection is secure and trusted.

   > **Still seeing a warning page?** Open a new Chrome tab, go to `chrome://certificate-manager/` → Trusted Root Certification Authorities tab → search for **Company**. If it's not listed, repeat the import steps above.

---

### macOS — Chrome

1. Double-click the **LAN-CA.crt** file — Keychain Access opens
2. Find **LAN CA** in the list and double-click it
3. Expand **Trust** → set **"When using this certificate"** to **Always Trust**
4. Close the window and enter your Mac password when prompted
5. Restart Chrome
6. Go to `https://192.0.2.10/assettracker/` — lock icon (🔒) in the address bar, no warning

---

### iPhone / iPad — Safari or Chrome

Both Safari and Chrome on iOS use the same system certificate store, so one install covers both browsers.

1. Open the **LAN-CA.crt** file from your email or Files app
2. A prompt appears: *"This website is trying to download a configuration profile"* — tap **Allow**
3. Go to **Settings → General → VPN & Device Management**
4. Tap the **LAN CA** profile → tap **Install** → enter your passcode → **Install** again
5. Go to **Settings → General → About → Certificate Trust Settings**
6. Find **LAN CA** and toggle it **ON**
7. Open Safari or Chrome and go to `https://192.0.2.10/assettracker/`

---

## Installing the app (after certificate is trusted)

### Windows — Chrome
- Look for the install icon **(⊕)** on the right side of the address bar
- Click it → **Install**
- The app opens in its own window and is pinned to your taskbar / Start menu

### macOS — Chrome
- Look for the install icon **(⊕)** on the right side of the address bar
- Click it → **Install**
- The app opens in its own window and appears in your Dock / Applications

### iPhone / iPad — Safari
- Tap the **Share** button (box with arrow) → **Add to Home Screen** → **Add**
- The app icon appears on your home screen

### iPhone / iPad — Chrome
- Tap the **three-dot menu** → **Add to Home Screen** → **Add**

---

## Renewal

The certificate expires **May 26, 2028**. End users do not need to do anything at renewal — only the server needs updating. Your device trust step is permanent.

---

## Questions?

Contact Justin — this takes about 2 minutes and the app works like any other installed app afterward.
