# rdp_pipe

Python desktop RDP client for Linux operators connecting to remote hosts over RDP with NLA (CredSSP) and NTLM password authentication. The UI is a native PyQt6 window with pointer-gated keyboard input and seamless resize via MS-RDPEDISP when the server supports it.

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
.venv/bin/rdp [-h] [--headless] [--pipe] [--no-autoresize] URL
```

GUI mode (default) opens a PyQt6 window. `--headless` runs without a display and **requires** `--pipe` for automation on `/tmp/rdp.sock`.

Press **Ctrl+C in the terminal** where you launched `rdp` to disconnect and exit cleanly (this does not affect keyboard input forwarded inside the session window).

`URL` is an aardwolf-style connection string or bare host shorthand:

```bash
.venv/bin/rdp rdp://DOMAIN\\Administrator@10.0.0.5:3389
.venv/bin/rdp rdp+ntlm-password://DOMAIN\\Administrator@10.0.0.5:3389
.venv/bin/rdp 10.0.0.5
```

Generic `rdp://` URLs prefer NTLM password authentication; the server selects NLA (CredSSP), TLS-only, or legacy RDP during X.224 negotiation.


### Server certificate trust

On NLA connect, the client stores the server TLS certificate under `~/.config/rdpipe/`:

- `clients/<ip>` — one-line file mapping the remote IP to a certificate fingerprint
- `certificates/<fingerprint>/` — `certificate` (PEM), `ip`, and `metadata` (JSON)

The first connection to an IP is accepted automatically. If the server later presents a different certificate for the same IP, the client refuses to connect and prints paths to remove, for example:

```text
~/.config/rdpipe/clients/10.0.0.5
~/.config/rdpipe/certificates/<old-fingerprint>/
```

Remove the `clients/<ip>` file to trust a new certificate on the next connect. IPv6 addresses use underscores instead of colons in client filenames (e.g. `2001_db8__1`).


### Password resolution

Passwords are resolved in order (first match wins):

1. Embedded in URL userinfo (`user:password@host`)
2. `RDP_PASSWORD` environment variable
3. Standard input — `getpass` on a TTY, otherwise one line from a pipe

If no password is available after these steps, the CLI exits with a non-zero status and an error on stderr.

Examples:

```bash
export RDP_PASSWORD='your-password'
.venv/bin/rdp 'rdp+ntlm-password://DOMAIN\Administrator@10.0.0.5'
```

```bash
echo 'your-password' | .venv/bin/rdp 'rdp+ntlm-password://Administrator@10.0.0.5'
```

### Headless automation

```bash
export RDP_PASSWORD='your-password'
.venv/bin/rdp --headless --pipe '10.0.0.5'
```

Headless mode uses a fixed 1280×800 session geometry (no window resize). The process listens on the Unix socket for newline-delimited JSON commands. Use `--color-depth 24` (or `16`) when you need a specific bpp for screen analysis via `receive_screenshot`.

Full wire format, command parameters, response shapes, and client examples: **[REMOTE_COMMAND_PROTOCOL.md](REMOTE_COMMAND_PROTOCOL.md)**.

Quick probe with `rdpr`:

```bash
.venv/bin/rdpr command_receive_geometry
.venv/bin/rdpr command_send_geometry 1920 1080
.venv/bin/rdpr command_send_click 640 400 --button left
.venv/bin/rdpr --sock-filepath /tmp/rdp.sock command_receive_screenshot --format png
```

Or with `nc`:

```bash
printf '%s\n' '{"command":"receive_geometry"}' | nc -U /tmp/rdp.sock
```

`--pipe` is optional in GUI mode (automation socket at `/tmp/rdp.sock` alongside the window).

## Monkey-patching

This client patches **aardwolf** at runtime instead of vendoring or forking the library. Patches live in production code under `src/rdp_pipe/` (not in tests). Each patch replaces a symbol on import; subclass overrides on `RdpDesktopConnection` are normal inheritance and are not listed here.

| Target | Replacement | Why |
|--------|-------------|-----|
| `aardwolf.protocol.T124.userdata.clientcoredata.TS_UD_CS_CORE.to_bytes` | `_patched_ts_ud_cs_core_to_bytes` in [`rdp_connection.py`](src/rdp_pipe/rdp_connection.py) | During desktop connect, advertise `SUPPORT_MONITOR_LAYOUT_PDU` and (when `--color-depth` is 32) `WANT_32BPP_SESSION` / 24-bpp high color in Client Core Data. Active only while `RdpDesktopConnection.connect()` runs (`_CONNECTING_DESKTOP_CONNECTION` gate). |
| `aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET.__init__` | `_patched_pointer_capabilityset_init` in [`rdp_connection.py`](src/rdp_pipe/rdp_connection.py) | Advertise `colorPointerFlag=True` so the server sends color/cached pointer updates for hover cursor shapes. |
| `aardwolf.connection.RDPConnection.handle_out_data` | `_patched_handle_out_data` in [`rdp_connection.py`](src/rdp_pipe/rdp_connection.py) | Before every Confirm Active (connect and mid-session reactivation), set `desktopResizeFlag=True` and add LARGE_POINTER / UNICODE / MOUSE_HWHEEL that aardwolf omits. |
| `RdpDesktopConnection._RDPConnection__process_fastpath` | `_rdp_desktop_process_fastpath` in [`rdp_connection.py`](src/rdp_pipe/rdp_connection.py) | Stock aardwolf handles fast-path `BITMAP` only. Our handler also forwards bitmap tiles without inferring resolution from tile size, and emits pointer updates (`COLOR`, `POINTER`, `CACHED`, etc.) for remote cursor mirroring. |
| `aardwolf.extensions.RDPECLIP.channel.RDPECLIPChannel._handle_format_data_request` | `_patched_rdpeclip_handle_format_data_request` in [`rdp_connection.py`](src/rdp_pipe/rdp_connection.py) | aardwolf dereferences `clipboard.data.datatype` without checking for `None`. After connect we advertise standard clipboard formats even when the local clipboard is empty; a remote `CB_FORMAT_DATA_REQUEST` then crashed the x224 reader. Reply with `CB_RESPONSE_FAIL` when `clipboard.data` is unset. |
| `aardwolf.connection.RDPConnection.terminate` | `_patched_aardwolf_terminate` in [`rdp_connection.py`](src/rdp_pipe/rdp_connection.py) | Stock aardwolf always calls `send_disconnect()` and logs `Error while requesting shutdown` when the MCS channel is missing (failed connect) or the TCP socket is already reset. Skip graceful shutdown when MCS/server connect data are absent; suppress the warning for expected transport errors during reconnect teardown. |

When adding or changing a runtime monkey-patch, update this section in the same change set.

## Test

```bash
./script/test.sh
```

Offline unit tests cover URL/password handling, RDPDISP PDU encoding, pointer mask decoding, command socket protocol, and CLI validation.

## Manual smoke

Connect to an RDP host with NLA enabled. Resize the client window and confirm the remote display resolution tracks when the server supports RDPDISP. Servers without RDPDISP keep a fixed session resolution; the local window may letterbox until disconnect.

To trace remote pointer mirroring (PDU types, apply/skip decisions, forwarded hover coordinates), run with `RDP_POINTER_DEBUG=1` and watch stderr while moving the mouse over window borders and text fields.
