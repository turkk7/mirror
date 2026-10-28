# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

مرآة الفوتوبوث — a smart-mirror photobooth. A Flask backend serves a full-screen vanilla-JS kiosk UI that runs in Chromium. The codebase is written with Arabic comments and Arabic-facing UI; keep new comments/strings consistent with that.

## Commands

```bash
./run.sh          # create .venv, install backend/requirements.txt, run server on :8000
./make_cert.sh    # generate self-signed HTTPS cert into certs/ (run once; see HTTPS note)
```

- Open the kiosk at `http://localhost:8000`; operator panel at `/admin` (default PIN `1234`).
- There is **no build step, no bundler, no npm** — the frontend is plain HTML/CSS/ES-modules served directly. Editing a file and reloading is the full dev loop.
- There is **no test suite and no linter** configured.
- `run.sh` must run from the repo root (it `cd`s into `backend/` and runs `python app.py`); the app entry point is `backend/app.py`.

## Configuration

All configuration is via `MIRROR_*` environment variables with dev-safe defaults in `backend/config.py`. The ones that change behavior the most:

- `MIRROR_MOCK` (default `1`) — mock-hardware mode; required `1` for dev on macOS (no real camera/printer).
- `MIRROR_CAMERA` — `webcam` (browser getUserMedia, the working default), `mock` (static sample), or `gphoto2` (DSLR — **not yet wired**).
- `MIRROR_ADMIN_PIN`, `MIRROR_PUBLIC_HOST`, `MIRROR_PORT`, `MIRROR_LATEST_TTL`, `MIRROR_LATEST_ONCE`.

## Architecture

**Single-kiosk, single-session device.** One Flask process per physical booth. Runtime state lives in memory; only operator settings are persisted.

- **`backend/app.py`** — the whole HTTP surface in one `create_app()`: serves the frontend, exposes the `/api/*` endpoints, and wires together the three stateful stores below. Hardware calls (camera capture, printing) are currently **stubs** that return mock responses; real `gphoto2` (capture) and CUPS (print) integration are the remaining hardware steps.
- **`backend/session.py`** (`Session`) — in-memory, lock-guarded session counters: capture quota, elapsed time, pause/end. **The package counts captures**: every successful capture (`/api/capture`, or `/api/capture/webcam` without the `recomposite` flag) calls `consume_capture()` and decrements `remaining` (retakes included). Printing/sharing do **not** decrement the package — `prints_used`/`shares_used` are stats only. The gphoto2 flow captures via `/api/capture` (which consumes) then re-uploads the brand-composited image via `/api/capture/webcam` with `recomposite: true` (which does **not** consume), so a DSLR shot counts once. This is the "package" accounting the operator manages.
- **`backend/photos.py`** (`PhotoStore`) — in-memory index of captured photos with **privacy as an invariant**: only **one photo is active at a time** — every new capture deletes the previous file and entry immediately — plus a TTL janitor thread that deletes expired files. Do not weaken this single-active-photo rule without understanding the NFC/QR privacy model it protects.
- **`backend/settings_store.py`** (`SettingsStore`) — operator settings persisted to `data/settings.json` via atomic temp-file replace. Only keys in `EDITABLE` can be changed through `PUT /api/settings`; `admin_pin` has its own guarded path. Guest-facing reads go through `public()` which strips the PIN.

**Two surfaces, two audiences.**
- **Guest kiosk** (`frontend/index.html`): the only thing on screen at the booth. Flow is attract → timer → flash → capture → result (print / digital copy / retake) → thank-you → attract. **The guest must never see operational data** (remaining quota, time, technical status) — that rule is load-bearing for the UX, enforced in `flow.js`.
- **Operator panel** (`/admin`, `admin.html` + `admin.js`): opened on the operator's own phone. Every mutating admin/session endpoint is authorized by an `X-Admin-Pin` request header checked against the stored PIN.

**Digital sharing / NFC.** After capture the photo is stored and a QR encodes `/p/<photo_id>` for the guest's phone. A stable `/latest` URL (written once to an NFC sticker) redirects to the most recent photo, gated by TTL and an optional one-time `claim` so a guest can't land on someone else's photo.

**Frontend module layout** (`frontend/js/`): `main.js` (entry) → `router.js` (screen switching) → `flow.js` (the capture/print/share state machine) → `camera.js` (getUserMedia capture, fixed 2:3 portrait output with mirror + overlay compositing) → `api.js` (fetch wrapper) + `helpers.js`. `admin.js` is the separate operator app.

## Non-obvious gotchas

- **getUserMedia requires a secure context** — it works on `http://localhost` but **not** over a LAN IP on plain HTTP. For on-device / cross-device use, generate certs with `make_cert.sh`; `app.py` auto-enables HTTPS when `certs/cert.pem` + `certs/key.pem` exist (also needed for iOS one-tap save).
- **Router selector trap**: the stage container uses `data-active`, while screen sections use `data-screen`, to avoid the container matching `[data-screen="..."]`. When wiring events, attach to `.screen[data-screen="..."]` (the section), not the container — see the note in `main.js`.
- `captures/`, `data/`, `certs/`, and `frontend/assets/overlay.png` are gitignored runtime artifacts.
- **Guest-kiosk visual tweaks for the booth** (in `frontend/`): the background is pure black (`--ink: #000` in `styles.css`) with the ambient color glows hidden — intentional so the two-way mirror stays reflective in the dark areas. The attract logo uses the hi-res transparent `assets/brand/qamra-lockup-hi.png` (extracted + upscaled from `qamra-lockup-dark.png`); the original `qamra-lockup.png` is low-res (178×266) and pixelates when scaled large. `index.html` carries `translate="no"` + `<meta name="google" content="notranslate">` to kill Chromium's translate bubble. The kiosk cursor-hide (`cursor: none` on `body` in `styles.css`) is **currently commented out for testing** — re-enable it for production touch use.

## Deployment status

The core guest flow, digital sharing, and operator panel are done, and a **live booth is now deployed and auto-starts on boot** (step 9 is largely complete). **Remaining hardware work**: step 5 (camera via `gphoto2` — a **Canon EOS 4000D** has now been purchased and is the single camera for both preview and final capture; `gphoto2`+`ffmpeg` are installed on the booth; the connect/test/wire-up procedure and the Live-View-vs-mirror-reflection decision are specced in `docs/camera-gphoto2.md`), and step 6 (printing via CUPS — needs a printer). Watchdog coverage is partial: the backend auto-restarts (`Restart=always`), but the Chromium kiosk process has no auto-restart yet.

### Live booth (production host)

The booth runs on a **2015 MacBook Pro (Intel) with Ubuntu 26.04.1 LTS**, GNOME on **Wayland**, Chromium (snap) in kiosk mode. (Earlier notes said Raspberry Pi / x86 mini-PC — the architecture is identical, only the host changed.) The laptop lid stays closed; its broken internal panel is disabled and a **portrait** TV on HDMI is the only display.

On-device layout — these files live on the booth under user `turkk`, **not** in this repo:
- **Project**: `/home/turkk/mirror`, deployed by `rsync` from the dev Mac (excluding `.venv/`, `captures/`, `data/`, `certs/`). Python venv is rebuilt on the booth (`python3.14-venv`).
- **Backend**: systemd service `qamra-backend.service` → `.venv/bin/python backend/app.py` with `MIRROR_DEBUG=0 MIRROR_MOCK=1 MIRROR_CAMERA=webcam`, `Restart=always`, enabled at boot.
- **Guest kiosk**: GDM **autologin** → GNOME Wayland session → autostart `~/.config/autostart/qamra-kiosk.desktop` runs `~/mirror/kiosk.sh`, which waits for `:8000` then launches `chromium --kiosk --app=http://localhost:8000 --ozone-platform=wayland` (translate/infobars/crash-bubble disabled). **Native Wayland (not Xwayland) is required** so the cursor and touch map correctly under display rotation.
- **Display**: portrait via `~/.config/monitors.xml` (rotation `right`, connector `HDMI-2`); the internal panel `eDP-1` is disabled at the kernel level (GRUB `video=eDP-1:d`); screen-blank/idle and system sleep are disabled (gsettings `idle-delay 0`, `sleep-inactive-ac-type nothing`, masked `sleep`/`suspend` targets); lid-close is ignored (`/etc/systemd/logind.conf.d/`).
- **Remote access**: key-only SSH (`ssh qamra` from the dev Mac → `turkk@192.168.1.147`). **Tailscale** (host `qamra`) makes the operator panel reachable from anywhere at `http://<tailscale-ip>:8000/admin` without exposing it publicly — important because `/admin` is PIN-only.
- **Caveats**: the operator PIN is still the default `1234` (change it); `ufw` is currently inactive; the battery no longer holds charge, so the booth powers off instantly when unplugged — it needs stable mains.

To push code to the booth: edit on the dev Mac, `rsync` the changed files to `qamra:mirror/...`, then activate the changes:
- **Backend changes** (`backend/`): `ssh qamra 'sudo systemctl restart qamra-backend.service'`. Relaunching `kiosk.sh` alone does **not** reload the backend — with `MIRROR_DEBUG=0` there is no auto-reloader, so edits stay inactive until the service restarts.
- **Frontend changes** (`frontend/`): relaunch `kiosk.sh` inside the Wayland session (or reload the kiosk) to pick up the new static files.
- **Either/both**: a full `reboot` restarts the backend service and the kiosk together.
