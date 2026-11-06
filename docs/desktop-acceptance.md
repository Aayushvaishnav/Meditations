# Packaged desktop acceptance (REV-14)

Use this runbook for a release candidate on a disposable graphical Linux session.
It specifies checks to perform; it is not evidence that any check has passed.
Browser tests, frozen-backend integration tests, and a development Tauri window
are not substitutes for these packaged native checks.

## Prepare an isolated run

- Use a disposable VM or dedicated OS test account with its own graphical login,
  session bus, and unlocked private Secret Service vault. **Changing `HOME` or
  XDG paths alone does not isolate Secret Service**: an inherited session bus can
  still reach the normal user's vault. A private D-Bus bus alone is insufficient
  unless a private credential service is actually running and usable there.
  Do not run against the normal user's bus, keyring, database, or credentials.
- Have the candidate package, its bundled backend, and an already available
  loopback CalDAV fixture ready. Do not install dependencies as part of this
  run. If a graphical session, vault, server, or native runtime is unavailable,
  mark the affected checks **BLOCKED**, rather than falling back to plaintext
  credentials or claiming browser coverage.
- Record release/tag and source commit (if known), artifact filename, SHA-256,
  acquisition URL or build command, build time, OS/architecture, desktop session,
  WebView/runtime version, and absolute launcher/backend paths. Confirm that
  both executables come from the same artifact, not a development checkout or
  unrelated executable on `PATH`. For an AppImage, keep its extracted resources
  available for the recovery command if necessary.

Inside the disposable session, create a private run directory; replace the
example path and executable paths with absolute paths for this run:

```bash
umask 077
export RUN=/absolute/private/desktop-acceptance-run
mkdir -p "$RUN"/{home,data,config,cache,state,backups,evidence}
export HOME="$RUN/home"
export XDG_DATA_HOME="$RUN/data"
export XDG_CONFIG_HOME="$RUN/config"
export XDG_CACHE_HOME="$RUN/cache"
export XDG_STATE_HOME="$RUN/state"
unset MEDITATIONS_LEGACY_DB JOURNAL_DB_PATH
export DB="$XDG_DATA_HOME/dev.journal.app/journal.db"
export LAUNCHER=/absolute/path/to/candidate-launcher
export BACKEND=/absolute/path/to/bundled/meditations-backend
sha256sum "$LAUNCHER" "$BACKEND"
"$LAUNCHER"
```

Retain the disposable login's valid `XDG_RUNTIME_DIR` and private session bus;
do not point them at another user's runtime. Launch every restart from this
same environment. Leave AI and outgoing webhooks unconfigured. Use only invented
content and passwords. Keep evidence private; do not record password fields or
vault contents. Backups and recovery checkpoints are unencrypted.

## Startup, close, and restart

1. Launch with no development API or Vite server running. Expect the packaged UI
   to become usable through its bundled backend on a random loopback port,
   without Python setup or a server at port 8000. Confirm the database is at
   `$DB`, not a normal profile path; record the child process and listening port.
2. Create a task named `rev14snapshot`, a journal containing `rev14journal`,
   ratings, and a saved work block. Wait for saves; navigate away and back to
   confirm persistence. Do not enable optional network features.
3. Close the main window. Confirm the window exits and its backend no longer
   owns `$DB` (inspect the recorded process and open-file ownership using
   available OS tools). Restart; expect the synthetic records intact. Repeat
   exit using tray **Quit** and confirm cleanup. A surviving owner is a failure
   to investigate, not permission to delete lock/WAL files.

## Native Save backup

Keep **Settings → Database backup** open during each attempt.

| Action | Expected observation |
|---|---|
| Choose **Save backup**, then cancel the native dialog | No new file, no success claim, UI usable; cancellation precedes the snapshot request. |
| Save to `$RUN/backups/snapshot.db`, a new name | Native dialog, successful save, nonempty file; on Linux inspect permissions for private creation. No browser download manager. |
| Hash `snapshot.db`; choose that same existing file again and accept any dialog overwrite prompt | App reports a write error; existing hash is unchanged. Exclusive creation rejects overwrite even if the dialog permits it. |
| Choose a new file inside a test directory made non-writable with `chmod 500` | Visible failure, not success; restore directory permissions with `chmod 700`, retry with a fresh filename, and expect success. Run unprivileged; if the dialog prevents selection, record that limitation and exercise a writable-path retry. |

Retain `snapshot.db` unchanged. Never select a real database as an overwrite
probe. Check failed attempts for partial files; preserve evidence and retry with
a new name rather than assuming a failed write cleaned up. Create a second task
`rev14later` after the snapshot; confirm it is saved before recovery testing.

## Offline bundled-backend recovery

Follow the [recovery contract](../README.md#restore-a-backup). Use the bundled
backend directly, not the desktop launcher, `uv`, Python, or an HTTP endpoint.
Block external networking in the disposable environment while leaving loopback
available; record how this was done. Recovery must not need a model download.

1. With the app still running, execute:

   ```bash
   "$BACKEND" restore "$RUN/backups/snapshot.db" --database "$DB"
   ```

   Expect nonzero exit and live-owner rejection. Confirm both tasks remain in
   the UI. Do not remove `.lock`, `-wal`, or `-shm` to bypass ownership.
2. Quit; confirm all owners of this test database are gone, including any
   standalone backend or SQLite viewer. Repeat the same command. Expect success
   and a printed pre-restore recovery-checkpoint path under the database's
   adjacent private `recovery/` directory. Record that exact path and confirm the
   file exists. If validation, checkpointing, or replacement fails, keep reported
   files and logs, resolve the stated cause, and retry only after inspection.
3. Restart through `$LAUNCHER`, still offline. Expect `rev14snapshot`, journal
   text/ratings, and the block restored; `rev14later` must be absent. Perform an
   exact keyword search for `rev14journal` in Second Brain and open its result.
   Keyword search must work after startup reconciliation. With a fresh cache
   and unavailable embedding model, semantic indexing/search may remain pending;
   record it separately, not as lost content or a passed semantic check.
4. Prove rollback: quit and restore the printed checkpoint using the same
   command with that file as the source. Restart; expect `rev14later` back.
   Record the new checkpoint too. Never restore over an open owner.

## Packaged WebView checks

Record these separately from backend recovery and any browser/automated results:

- Navigate Tasks, Journal, Second Brain, and Settings; type/save/reopen the
  synthetic journal. Expect responsive navigation, persisted content, and no
  blank screen or broken packaged assets while external networking is blocked.
- Exercise the native backup dialog and error recovery above inside this WebView;
  browser download behavior is not a pass for Tauri dialog/filesystem access.
- Verify tray show/focus and `Super+Shift+A` focus behavior. Record a desktop
  shortcut conflict or missing tray support as BLOCKED for that check, with the
  environment limitation; do not infer a backend failure.

## Synthetic CalDAV and private vault

Use an already provisioned, separately managed loopback fixture, such as the
[Radicale configuration](calendar-sync.md#optional-linux-user-service). Keep its
configuration, collections, and authentication file in this run's private area;
use a fresh account and writable event calendar containing only synthetic data.
Bind to `127.0.0.1` on an unused port, never a public interface. Record fixture
version, URL, calendar identity, and server log location, but not passwords.
If unavailable, mark this section BLOCKED; do not install it or connect a real
account as a substitute. Permit loopback while external networking stays blocked.

1. In **Settings → Calendar synchronization**, select **New server**, enter the
   loopback URL and synthetic account, select its authentication method, discover
   calendars, select the test calendar, and **Connect and save credentials**.
   Expect confirmed credential storage and sync paused. Discovery alone does not
   pass the native vault check. Opening Settings alone must not trigger remote
   verification or a vault unlock.
2. Explicitly publish the synthetic block, **Enable sync**, then **Sync now**.
   Confirm acknowledgment and the matching event in the fixture's independent
   client. Create a synthetic remote appointment there; select **Live calendar**
   in Calendar and confirm its read-only mirrored appearance without a new task.
3. Save a new backup `calendar-connected.db`. Quit and restart. Expect remote
   activity disabled; review pending intent and calendar identity, choose
   **Verify connection**, then explicitly enable sync. Expect private vault
   credentials to work without reentry at the same database path. Confirm a new
   fixture-side change is mirrored after verification, not just an old cache.
4. Quit, restore `calendar-connected.db` using the bundled offline command, and
   restart. Again expect remote activity disabled until explicit verification
   and enablement; review restored queues before enabling. Confirm an actual
   round trip. Backups exclude CalDAV secrets: same-path credentials may still
   exist in the vault, but moving to another database path changes their
   namespace. If credentials are unavailable, select the existing connection,
   reenter the synthetic credentials, discover/connect, then verify and enable.
5. Choose **Disconnect**. Expect activity stopped, mappings detached, credentials
   removed, and remote events retained. Restart and confirm no automatic resume;
   reconnecting requires credentials. If removal is incomplete, unlock the
   private vault and retry Disconnect until confirmed; retain failure evidence.

Actual providers are **optional and opt-in only**: obtain explicit authorization,
use a dedicated disposable account/calendar, document the provider separately,
and repeat the relevant checks. This run establishes no general Nextcloud,
Baïkal, or other provider compatibility claim.

## Record the result

For each section record **PASS**, **FAIL**, or **BLOCKED**, observations, evidence
paths, and artifact hash. PASS requires observing every applicable expectation;
FAIL is observed incorrect behavior; BLOCKED means a prerequisite or environment
prevented execution. Leave unexecuted checks explicitly unexecuted. Report
keyword recovery and semantic readiness independently. Preserve private failure
logs/checkpoints before cleanup; disconnect the synthetic account, stop the test
server, and dispose of the test session/profile/vault when evidence is secured.
Do not delete or inspect anything in the normal user profile.
