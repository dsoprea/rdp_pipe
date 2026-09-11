# Features

## CLI (`rdp`)

- Positional RDP URL (aardwolf `rdp+ntlm-password://` form or bare host normalized to that scheme)
- Password from URL userinfo, `RDP_PASSWORD`, or stdin (`getpass` on a TTY; one line when piped)
- Exits non-zero with a clear stderr message when password resolution fails
- `--headless`: console-only mode (no PyQt6 window); requires `--command-socket`
- `--command-socket PATH`: Unix domain socket for JSON-line automation (optional in GUI mode, mandatory with `--headless`)

## Command socket (automation)

- Newline-delimited JSON, one client at a time
- `receive_screenshot`: remote framebuffer as base64 PNG/JPEG (`format`, `quality`)
- `send_click`: mouse click at remote coordinates (`x`, `y`, `button`: left/right/middle)
- `receive_geometry`: `width`, `height`, `color_depth`
- `send_key`: type text (`keys`) or press a named key (`key`, e.g. `Return`, `Escape`)
- Automation input bypasses pointer-inside-canvas gating used by the GUI

## Headless mode

- No display server required; fixed 1280×800 connect resolution
- Connection progress steps printed to stderr (prepare, connect, certificate trust, authentication, display configuration, ready)
- Serves the command socket until the RDP session ends

## Desktop session (PyQt6)

- Connecting overlay: dimmed full-window modal centered on the session window listing connect steps (prepare, TCP/TLS, certificate trust, authentication, display configuration) until the session is ready
- Resizable native window (default 1280×800) showing the remote framebuffer at 1:1 pixels (letterboxed when local and remote sizes differ)
- Mouse move, press, release, and wheel forwarded while the cursor is over the canvas (no mouse grab)
- Keyboard forwarded only while the pointer is inside the canvas
- Partial framebuffer updates from aardwolf `RDP_VIDEO` rectangles

## Seamless resize (MS-RDPEDISP)

- Registers dynamic virtual channel `Microsoft::Windows::RDS::DisplayControl`
- Advertises monitor-layout and 32 bpp session capability flags at connect
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
