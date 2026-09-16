# Features

## CLI (`rdp`)

- Positional RDP URL (`rdp://`, explicit `rdp+ntlm-password://`, or bare host normalized to `rdp+ntlm-password://`; generic `rdp://` prefers NTLM and follows the server's X.224 protocol choice)
- Password from URL userinfo, `RDP_PASSWORD`, or stdin (`getpass` on a TTY; one line when piped)
- Exits non-zero with a clear stderr message when password resolution fails
- `--headless`: console-only mode (no PyQt6 window); requires `--pipe`
- `--pipe`: Unix domain socket for JSON-line automation at `{system temp}/rdp.sock` (optional in GUI mode, mandatory with `--headless`)
- Touches `{system temp}/rdp_activity.stamp` on each remote framebuffer update (for external watchdogs / idle detection)
- `--color-depth N`: session bits per pixel (`15`, `16`, `24`, or `32`; default `32`); sets `receive_geometry.color_depth` and the framebuffer used by `receive_screenshot`
- Terminal Ctrl+C (SIGINT in the launching shell) disconnects cleanly and exits without a traceback in GUI and headless modes
- Connect failures print a single managed stderr `error:` line with `host:port` and a short reason (no traceback); certificate fingerprint mismatch keeps the multi-line remediation format
- `--viewer`: ignore local mouse and keyboard input (screen updates only); command-pipe automation is unchanged — for auditing a session without affecting it

## CLI (`rdpr`)

Send one automation command to a running `rdp` session (started with `--pipe`):

- `--sock-filepath PATH`: Unix domain socket (default `{system temp}/rdp.sock`)
- Subcommands (wire names prefixed with `command_`): `command_receive_geometry`, `command_send_geometry`, `command_receive_screenshot`, `command_send_click`, `command_send_key`
- Writes the full JSON response envelope to stdout for most subcommands (`{"ok": true, "result": {...}}` or error via stderr with exit code `1`); `command_receive_screenshot` by default writes decoded image bytes to a temporary file, prints the filepath on stdout, and prints `Image size: SIZE` (megabytes, two decimal places) plus a trailing blank line on stderr — pass `--no-write` to print the JSON envelope instead
- One invocation sends one command; see [REMOTE_COMMAND_PROTOCOL.md](REMOTE_COMMAND_PROTOCOL.md) for wire field details

## MCP (`rdp_pipe`)

Model Context Protocol server for LLM hosts (Cursor and others) that wraps `rdpr` subcommands:

- Project config: [`mcp/mcp.json`](mcp/mcp.json) (`mcp/run_server.sh`; copy to `.cursor/mcp.json` for Cursor or merge into other hosts)
- Launcher: `mcp/run_server.sh` (pyenv + `RDPR_COMMAND` wiring); server module: `mcp/server.py` (stdio transport)
- Prerequisite: `rdp` running with `--pipe` on the command socket (default `{system temp}/rdp.sock`)
- Install MCP support: `pip install -e ".[mcp]"` (after pyenv install per `.python-version`)
- Environment: `RDPR_COMMAND` (default `rdpr` on `PATH`), `RDPR_SOCK_FILEPATH` (default `{system temp}/rdp.sock`)
- Tools (one per `rdpr` subcommand): `command_receive_geometry`, `command_send_geometry`, `command_receive_screenshot`, `command_send_click`, `command_send_key`
- `command_receive_screenshot` always invokes `rdpr` with `--no-write` and returns inline MCP image content plus width/height metadata (no temporary image file)
- Other tools return the full JSON response envelope as text

## Command socket (automation)

Wire protocol reference: [REMOTE_COMMAND_PROTOCOL.md](REMOTE_COMMAND_PROTOCOL.md).

- Newline-delimited JSON, one client at a time
- `receive_screenshot`: remote framebuffer as base64 PNG/JPEG (`format`, `quality`)
- `send_click`: mouse click at remote coordinates (`x`, `y`, `button`: left/right/middle)
- `receive_geometry`: `width`, `height`, `color_depth`
- `send_geometry`: reconfigure remote resolution (`width`, `height`; omit both to reset to native connect resolution)
- `send_key`: type text (`keys`) or press a named key (`key`, e.g. `Return`, `Escape`)
- Automation input bypasses pointer-inside-canvas gating used by the GUI

## Headless mode

- No display server required; fixed 1280×800 connect resolution
- Connection progress steps printed to stderr (prepare, connect, certificate trust, authentication, display configuration, ready)
- Connect failures exit non-zero with the same managed `error: could not connect to host:port (reason)` stderr line as the GUI (no traceback)
- Serves the command socket until the RDP session ends
- **Stdout transaction log:** one JSON object per line for every socket command (`timestamp`, `command`, `request_size`, `response_size`, `response_success`, `transaction_duration_seconds` with two decimal places); stderr remains human progress and error messages only

## Desktop session (PyQt6)

- Window title `RDP - <host>` where `<host>` is the connection hostname from the CLI URL argument
- Connecting overlay: dimmed full-window modal centered on the session window listing connect steps (prepare, TCP/TLS, certificate trust, authentication, display configuration) until the session is ready
- Shutting-down overlay: dimmed modal with indeterminate progress while the client disconnects and background threads exit
- Resizable native window (default 1280×800) showing the remote framebuffer at 1:1 pixels (letterboxed when local and remote sizes differ)
- Mouse move, press, release, double-click, and wheel forwarded while the cursor is over the canvas (no mouse grab); suppressed when `--viewer` is set
- `RDP_MOUSE_DEBUG=1`: stderr trace of Qt mouse/context-menu events and mapped RDP button state (for diagnosing click issues)
- Remote cursor shapes mirrored from the server (resize, I-beam, hand, etc.) via RDP pointer updates
- Keyboard forwarded only while the pointer is inside the canvas; suppressed when `--viewer` is set
- Partial framebuffer updates from aardwolf `RDP_VIDEO` rectangles
- Remote desktop wallpaper when the server provides it (client does not request `DISABLE_WALLPAPER` at connect)
- Closing the window sends an RDP disconnect and waits for the session to end before the process exits
- Automatic reconnect: when the server drops or restarts, the client shows a reconnecting overlay, prints a managed stderr line (`error: RDP session to host:port disconnected; reconnecting...`), and retries until the session is back or the operator closes the window / presses Ctrl+C
- Clipboard sync (text only): local Qt clipboard changes are forwarded to the remote session; remote copy updates the local clipboard (Unicode text via RDPECLIP)

## Seamless resize (MS-RDPEDISP)

- Registers dynamic virtual channel `Microsoft::Windows::RDS::DisplayControl`
- Advertises monitor-layout capability at connect; requests 32 bpp session flags when `--color-depth` is `32` (default)
- Debounced window resize (~250 ms) sends `DISPLAYCONTROL_MONITOR_LAYOUT_PDU`
- `--no-autoresize` keeps the remote resolution fixed while the local window still letterboxes
- Reallocates local desktop buffer when the server changes session geometry
- Falls back to letterboxing when the server does not send RDPDISP caps (warning logged once)


## Server certificate trust (TOFU)

- TLS server certificates stored under `~/.config/rdpipe/` during NLA/CredSSP connect
- First connection to an IP auto-accepts the presented certificate (trust on first use)
- Repeat connections require the same SHA-256 certificate fingerprint for that IP
- Fingerprint mismatch aborts connect and prints remediation paths on stderr (remove `clients/<ip>` to re-trust)
- Certificate PEM, remote IP, and JSON metadata stored per fingerprint under `certificates/<fingerprint>/`

## Authentication scope

- NLA / CredSSP with NTLM password URLs (`rdp+ntlm-password://`)
- Remote host must offer NLA (CredSSP) compatible with aardwolf’s NTLM password auth

## Known limitations

- RDPDISP requires server support; some RDP implementations do not advertise display control and will not resize remotely
- Clipboard file lists and non-text formats are not synced; multi-monitor, drive redirection, and RemoteApp (RAIL) are not implemented
- aardwolf bitmap rendering path only; modern GFX/H.264 remoting may not apply
