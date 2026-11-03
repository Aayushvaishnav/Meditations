# Calendar synchronization

Publish selected Journal work blocks to a CalDAV calendar that you manage. Local-only use needs no account or server. There is no Journal account to create.

Journal is a calendar client. It does not bundle, install, configure, or start a CalDAV server. Your server runs independently. Journal synchronizes only while its backend is running; quitting the desktop app stops synchronization. Other calendar apps connect to the same server, instead of connecting to Journal.

## Choose a server

You can use an independently installed, user-managed [Radicale](https://radicale.org/v3.html) server. Installation, upgrades, backups, access control, and availability are your responsibility. Follow the official [installation and configuration guide](https://radicale.org/v3.html#documentation); package names, executable paths, and service conventions vary by distribution.

Use **HTTPS** for a remote server. HTTP is accepted only for loopback, for example `http://127.0.0.1:5232/`. A loopback server is useful on one computer, but your phone cannot reach that computer using the phone's own `localhost`. To share events with a phone or another computer, provide a shared server address reachable by all devices, with HTTPS and appropriate authentication. Configure those devices with that server's account and calendar.

### Optional Linux user service

This example assumes you have already installed Radicale and its bcrypt authentication support using your distribution's packages or another installation method from the official guide. It does not install anything. Check the paths with your installation before using it.

Create private configuration and storage directories:

```bash
install -d -m 700 "$HOME/.config/radicale" "$HOME/.local/share/radicale/collections"
```

Use the system `htpasswd` utility (commonly supplied by Apache utilities) to create a bcrypt password file. Enter the password at the prompt; keep it out of shell arguments and history:

```bash
htpasswd -c -B "$HOME/.config/radicale/users" calendaruser
chmod 600 "$HOME/.config/radicale/users"
```

Use `-c` only when creating a new file. To change a password or add another user, omit `-c` so existing entries are preserved. Do not use `htpasswd -b`.

Save this as `~/.config/radicale/config`, replacing `/home/YOUR_USER` with your actual absolute home path:

```ini
[server]
hosts = 127.0.0.1:5232

[auth]
type = htpasswd
htpasswd_filename = /home/YOUR_USER/.config/radicale/users
htpasswd_encryption = bcrypt

[rights]
type = owner_only

[storage]
filesystem_folder = /home/YOUR_USER/.local/share/radicale/collections
```

This configuration is **loopback-only**. For remote access, follow Radicale's official [reverse-proxy guidance](https://radicale.org/v3.html#documentation/reverse-proxy) and configure HTTPS, authentication, and network access before exposing it. Do not simply expose this HTTP listener to the internet.

Create `~/.config/systemd/user/radicale.service` (create the directory first if needed):

```ini
[Unit]
Description=Personal Radicale calendar server

[Service]
ExecStart=/usr/bin/radicale --config %h/.config/radicale/config
Restart=on-failure

[Install]
WantedBy=default.target
```

Replace `/usr/bin/radicale` with your installed executable's absolute path. Then start the service yourself:

```bash
systemctl --user daemon-reload
systemctl --user enable --now radicale.service
systemctl --user status radicale.service
```

A user service normally follows your login session. If it must remain available after logout, review your distribution's user-service and lingering policy. Journal never manages this service. Open Radicale's web interface in a browser, sign in, and create a dedicated event calendar, such as **Meditations**, before connecting Journal.

## Connect in Settings

1. Open **Settings → Calendar synchronization**.
2. Under **Set up or replace credentials**, choose **New server** in **Connection**.
3. Enter **Server URL**, **Username**, and **Password or app password**. Choose the server's method under **Authentication**. The Radicale htpasswd example above uses **Basic**. OAuth-only sign-in is unsupported.
4. Choose **Discover calendars**. In **Remote calendar**, choose a writable event calendar.
5. Choose **Connect and save credentials**.

Credentials are stored by the backend in your OS credential store, separate from SQLite backups and portable exports. Keep the OS vault available and unlocked. Discovery succeeding alone does not confirm that credentials were saved; check the result of connecting. Native vault behavior still needs desktop verification on your system.

Setup leaves synchronization paused and blocks unselected. Opening Settings does not automatically contact the server or unlock the vault.

## Publish selected work blocks

1. Choose a saved block under **Time block to publish**.
2. Choose **Publish selected block**.
3. Choose **Enable sync**. Use **Sync now** to request a pass without waiting for the worker.
4. Check the queued, conflict, and error counts and **Last successful sync**. Confirm the event in another client connected to the same server.

Only explicitly selected blocks enter the queue. Enabling sync selects nothing automatically. Each block becomes an independent iCalendar **VEVENT**, an appointment, instead of a **VTODO** task. Deadlines alone do not publish events. Journal does not import remote tasks or appointments into its task list.

Timed blocks preserve their instants; receiving clients display them in their chosen timezone. All-day blocks preserve calendar dates with an exclusive end. Task completion leaves the appointment **CONFIRMED**; cancellation makes it **CANCELLED**. Completion does not delete the event. Task recurrence does not become event recurrence, and successors receive no blocks automatically. Calendar recurrence, series editing, and invitations are unsupported.

Local saves are immediate; remote success requires server acknowledgment. A completed **Sync now** request can still leave conflicts or errors to resolve.

## Pause, remove, or disconnect

| Control | Result |
|---|---|
| **Pause sync** | Stops remote activity while keeping queued intent. Local edits continue to queue for selected blocks. |
| **Enable sync** | Resumes an explicitly verified connection without selecting new blocks. |
| **Remove remote event** | Queues deletion of that block's remote event while keeping local data. Offline deletion waits for the server. |
| **Stop syncing; keep remote** | Detaches the link and retains the remote copy. Further writes through that link stop. |
| **Disconnect** | Stops activity, detaches mappings, and removes saved OS credentials. Remote events remain. |

If you want remote events removed, use **Remove remote event** and wait for **Remote removal complete** before disconnecting. Detached or disconnected mappings cannot silently resume. A completed removal can be selected again with **Publish selected block**.

## Restart, restore, and connection problems

After restarting Journal or restoring a database, remote activity is disabled. Choose **Verify connection**, then **Enable sync** when ready. A restored database can contain old queued intent; review the selected calendar and pending work first. If credentials are unavailable, including after moving a database to another path or machine, select the existing **Connection** under **Set up or replace credentials**, enter credentials, discover the calendar, and connect again. Re-enable sync explicitly.

When offline, queued work stays local until the connection is available. If authentication fails, replace credentials or verify them, then enable sync again. Check the server's address, HTTPS configuration, service status, and OS vault if verification fails.

A **conflict** means Journal cannot safely update or remove the remote resource, for example after another client edits it. Journal does not force an overwrite. Inspect both copies in Journal and your other calendar client. Use **Stop syncing; keep remote** to detach safely, then resolve differences manually in the appropriate app. Detachment stops synchronization; it does not merge copies or make that block eligible for automatic republication.

If Settings reports **Credential removal incomplete. Retry Disconnect.**, unlock or repair access to the OS credential store and choose **Disconnect** again. Remote events remain untouched; do not assume credentials have been removed until the retry succeeds.

## Verification scope

Real-HTTP integration checks target **Radicale 3.9.0**: discovery, authentication, conditional writes and conflicts, response-loss recovery, offline/restart behavior, DST boundaries, and all-day dates. Packaged-backend discovery targets a local test server only. Native OS vault integration and the full desktop workflow remain unverified. These checks do not establish compatibility with every calendar client or deployment configuration.

**Nextcloud and Baïkal have not been verified.** No support claim is made for them. Use the verified Radicale scope as a starting point and test your own server and clients before relying on synchronization.

### Developer verification

From `backend/`, run the isolated local-server integration suite:

```bash
uv run --locked --group calendar-test pytest integration/test_radicale.py
```

The `calendar-test` dependency group pins Radicale 3.9.0 for testing only; it is separate from the shipped application. To include frozen-backend discovery, provide an absolute path to an already-built sidecar:

```bash
JOURNAL_TEST_SIDECAR=/absolute/path/to/meditations-backend \
  uv run --locked --group calendar-test pytest integration/test_radicale.py
```

Without that variable, the packaged-discovery case is skipped. The release gate invokes the same integration command with the frozen executable before desktop bundling. It verifies local-server interoperability, instead of native vault or full desktop operation.
