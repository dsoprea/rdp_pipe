# Features

## CLI (`rdp`)

- Positional RDP URL (aardwolf `rdp+ntlm-password://` form or bare host normalized to that scheme)
- Password from URL userinfo, `RDP_PASSWORD`, or stdin (`getpass` on a TTY; one line when piped)
- Exits non-zero with a clear stderr message when password resolution fails
- `--headless`: console-only mode (no PyQt6 window); requires `--pipe`
- `--pipe`: Unix domain socket for JSON-line automation at `/tmp/rdp.sock` (optional in GUI mode, mandatory with `--headless`)
- `--activity-stamp-filepath PATH`: touch `PATH` on each remote framebuffer update (for external watchdogs / idle detection)
- `--color-depth N`: session bits per pixel (`15`, `16`, `24`, or `32`; default `32`); sets `receive_geometry.color_depth` and the framebuffer used by `receive_screenshot`
- Terminal Ctrl+C (SIGINT in the launching shell) disconnects cleanly and exits without a traceback in GUI and headless modes

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
- Serves the command socket until the RDP session ends

## Desktop session (PyQt6)

- Window title `RDP - <host>` where `<host>` is the connection hostname from the CLI URL argument
- Connecting overlay: dimmed full-window modal centered on the session window listing connect steps (prepare, TCP/TLS, certificate trust, authentication, display configuration) until the session is ready
- Resizable native window (default 1280×800) showing the remote framebuffer at 1:1 pixels (letterboxed when local and remote sizes differ)
- Mouse move, press, release, and wheel forwarded while the cursor is over the canvas (no mouse grab)
- Remote cursor shapes mirrored from the server (resize, I-beam, hand, etc.) via RDP pointer updates
- Keyboard forwarded only while the pointer is inside the canvas
- Partial framebuffer updates from aardwolf `RDP_VIDEO` rectangles
- Remote desktop wallpaper when the server provides it (client does not request `DISABLE_WALLPAPER` at connect)
- Closing the window sends an RDP disconnect and waits for the session to end before the process exits

## Seamless resize (MS-RDPEDISP)

- Registers dynamic virtual channel `Microsoft::Windows::RDS::DisplayControl`
- Advertises monitor-layout capability at connect; requests 32 bpp session flags when `--color-depth` is `32` (default)
- Debounced window resize (~250 ms) sends `DISPLAYCONTROL_MONITOR_LAYOUT_PDU`
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
- Clipboard, multi-monitor, drive redirection, and RemoteApp (RAIL) are not implemented
- aardwolf bitmap rendering path only; modern GFX/H.264 remoting may not apply
