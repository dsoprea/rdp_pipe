# rdp_client

Python desktop RDP client for Linux operators connecting to Windows hosts with NLA (CredSSP) and NTLM password authentication. The UI is a native PyQt6 window with pointer-gated keyboard input and seamless resize via MS-RDPEDISP when the server supports it.

## Prerequisites

- Python 3.11+
- An X11 or Wayland desktop session for PyQt6
- Network reachability to the target host on TCP 3389 (or the port in the URL)

## Install

```bash
./script/install.sh
```

This creates `.venv/` and installs the package in editable mode with test dependencies.

## Connect

```bash
.venv/bin/rdp_connect [-h] [--headless] [--command-socket PATH] URL
```

GUI mode (default) opens a PyQt6 window. `--headless` runs without a display and **requires** `--command-socket` for automation.

`URL` is an aardwolf-style connection string or bare host shorthand:

```bash
.venv/bin/rdp_connect rdp+ntlm-password://DOMAIN\\Administrator@10.0.0.5:3389
.venv/bin/rdp_connect 10.0.0.5
```

### Password resolution

Passwords are resolved in order (first match wins):

1. Embedded in URL userinfo (`user:password@host`)
2. `RDP_PASSWORD` environment variable
3. Standard input — `getpass` on a TTY, otherwise one line from a pipe

If no password is available after these steps, the CLI exits with a non-zero status and an error on stderr.

Examples:

```bash
export RDP_PASSWORD='your-password'
.venv/bin/rdp_connect 'rdp+ntlm-password://DOMAIN\Administrator@10.0.0.5'
```

```bash
echo 'your-password' | .venv/bin/rdp_connect 'rdp+ntlm-password://Administrator@10.0.0.5'
```

### Headless automation

```bash
export RDP_PASSWORD='your-password'
.venv/bin/rdp_connect --headless --command-socket /tmp/rdp.sock '10.0.0.5'
```

Headless mode uses a fixed 1280×800 session geometry (no window resize). The process listens on the Unix socket for newline-delimited JSON commands.

Example request (one line per command):

```bash
printf '%s\n' '{"command":"receive_geometry"}' | nc -U /tmp/rdp.sock
```

Commands: `receive_screenshot` (`format` default `png`, `quality` default `9`), `send_click` (`x`, `y`, `button`), `receive_geometry`, `send_key` (`keys` or `key`). Responses are JSON lines: `{"ok": true, "result": {...}}` or `{"ok": false, "error": "..."}`.

`--command-socket` is optional in GUI mode (automation socket alongside the window).

## Test

```bash
./script/test.sh
```

Offline unit tests cover URL/password handling, RDPDISP PDU encoding, command socket protocol, and CLI validation.

## Manual smoke

Connect to a Windows 10/11 or Windows Server host with NLA enabled. Resize the client window and confirm the remote display resolution tracks (remote Display Settings or `GetScreenResolution` in PowerShell). RDPDISP requires server support (Windows 8 / Server 2012+); many XRDP builds do not advertise display control.
