# Remote command protocol

Automation clients drive an active RDP session through a **Unix domain stream socket** using **newline-delimited JSON**. Each request is one UTF-8 line; each response is one UTF-8 line. The protocol is implemented by `rdp_pipe.command_socket.CommandSocketServer` and is available when the `rdp` CLI is started with `--pipe`.

## Enabling the socket

| Mode | Flag | Socket path |
|------|------|-------------|
| Headless (required) | `--headless --pipe` | `/tmp/rdp.sock` |
| GUI (optional) | `--pipe` | `/tmp/rdp.sock` |

Headless mode connects at a fixed **1280×800** session geometry. GUI mode may resize the remote desktop via MS-RDPEDISP when the server supports it; `receive_geometry` and `receive_screenshot` always reflect the current remote session size.

The socket is created only after the RDP session connects successfully. In headless mode, connection progress is printed to stderr before the line `listening on /tmp/rdp.sock`.

## Transport semantics

- **Socket type:** `AF_UNIX` `SOCK_STREAM`
- **Encoding:** UTF-8 text
- **Framing:** one JSON object per line, terminated by `\n` (JSON Lines / NDJSON style)
- **Concurrency:** one connected client at a time; additional clients block in `accept` until the current client disconnects
- **Request order:** strictly sequential per connection — the server reads a line, writes the response line, then reads the next request
- **Disconnect:** when the client closes the write side (or sends EOF), the server stops reading and accepts the next client
- **Command timeout:** each command is executed on the RDP asyncio event loop with a **30 second** wall-clock limit; overrun surfaces as a socket-level failure rather than a JSON error response

On startup, if `/tmp/rdp.sock` already exists, it is removed before `bind`.

## Message envelope

### Request

Every request is a JSON object with a required `command` string. Additional fields depend on the command.

```json
{"command":"<name>", ...}
```

### Success response

```json
{"ok":true,"result":{...}}
```

`result` is always a JSON object. Commands that perform an action with no return payload use an empty object: `{}`.

### Error response

```json
{"ok":false,"error":"<human-readable message>"}
```

Errors are returned for:

- Empty request lines
- Invalid JSON
- Missing `command` field
- Unknown `command` name
- Invalid or incomplete command parameters (`ValueError`, `RdpInputError`)
- Session state problems (`RdpSessionError`, e.g. desktop buffer not ready)
- Unexpected internal failures (`command failed: …`)

Parse and validation errors do **not** close the connection; the client may send another request on the same socket.

## Coordinate system

Mouse commands use **remote desktop coordinates**: origin at the top-left of the session framebuffer, **x** increasing right, **y** increasing down. Values are integers in the range implied by `receive_geometry` (`0 … width-1`, `0 … height-1`). Automation input is **not** gated on pointer-inside-canvas checks (unlike the PyQt6 GUI).

## Commands

### `receive_geometry`

Return the current remote session dimensions and color depth.

**Request**

```json
{"command":"receive_geometry"}
```

**Result**

| Field | Type | Description |
|-------|------|-------------|
| `width` | number | Session width in pixels |
| `height` | number | Session height in pixels |
| `color_depth` | number | Bits per pixel (`15`, `16`, `24`, or `32`; from `--color-depth`) |

**Example**

```json
{"ok":true,"result":{"width":1280,"height":800,"color_depth":32}}
```

---

### `send_geometry`

Request a remote desktop resolution change via MS-RDPEDISP (`DISPLAYCONTROL_MONITOR_LAYOUT_PDU`). Requires the server to advertise RDPDISP caps at connect; otherwise the command fails.

**Request**

| Field | Required | Description |
|-------|----------|-------------|
| `command` | yes | `"send_geometry"` |
| `width` | no* | Target width in pixels |
| `height` | no* | Target height in pixels |

\* Omit **both** `width` and `height` to reset to the **native** (initial connect) resolution — `1280×800` in headless mode, or the window size passed at session start in GUI mode. Supply **both** to set an explicit size. Supplying only one dimension is an error.

Width is clamped to `200–8192` and forced **even**; height is clamped to `200–8192`.

```json
{"command":"send_geometry","width":1920,"height":1080}
```

```json
{"command":"send_geometry"}
```

**Result**

| Field | Type | Description |
|-------|------|-------------|
| `width` | number | Width sent to the server after clamping |
| `height` | number | Height sent to the server after clamping |

**Errors**

- `send_geometry requires both width and height, or neither to reset native resolution`
- `RDPDISP display control is not available; cannot change remote resolution`

**Example**

```json
{"ok":true,"result":{"width":1920,"height":1080}}
```

---

### `receive_screenshot`

Capture the current remote framebuffer and return it as base64-encoded image bytes.

**Request**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `command` | yes | — | `"receive_screenshot"` |
| `format` | no | `"png"` | `"png"`, `"jpeg"`, or `"jpg"` (jpeg aliases) |
| `quality` | no | `9` | PNG: zlib compress level `0–9`. JPEG: quality `1–95` (values outside range are clamped) |

```json
{"command":"receive_screenshot","format":"png","quality":9}
```

**Result**

| Field | Type | Description |
|-------|------|-------------|
| `width` | number | Session width when the image was captured |
| `height` | number | Session height when the image was captured |
| `format` | string | Normalized format (`png` or `jpeg`) |
| `data` | string | Standard base64 (RFC 4648) encoding of the image file bytes |

The image is converted to **RGB** before encoding. PNG uses PIL `compress_level`; JPEG uses PIL `quality`.

**Errors**

- `desktop buffer has no image data yet` — no framebuffer received from the server yet
- `desktop buffer could not be read` — buffer present but unreadable
- `unsupported image format …; use png or jpeg`

**Example**

```json
{"ok":true,"result":{"width":1280,"height":800,"format":"png","data":"iVBORw0KGgoAAAANSUhEUgAA..."}}
```

---

### `send_click`

Send a mouse button press and release at `(x, y)`.

**Request**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `command` | yes | — | `"send_click"` |
| `x` | yes | — | Horizontal pixel coordinate |
| `y` | yes | — | Vertical pixel coordinate |
| `button` | no | `"left"` | `"left"`, `"right"`, or `"middle"` (case-insensitive) |

```json
{"command":"send_click","x":640,"y":400,"button":"left"}
```

**Result**

```json
{}
```

**Errors**

- `send_click requires x and y`
- `unsupported mouse button …; use left, right, or middle`

---

### `send_key`

Send keyboard input as either literal text or a single named key.

**Request**

Supply **exactly one** of:

| Field | Description |
|-------|-------------|
| `keys` | Unicode string; each character is sent as press+release unicode scancodes |
| `key` | Named special key (see table below) |

```json
{"command":"send_key","keys":"hello"}
```

```json
{"command":"send_key","key":"Return"}
```

**Result**

```json
{}
```

**Errors**

- `send_key requires keys or key`
- `send_key accepts keys or key, not both`
- `unsupported key name …`

#### Named keys (`key` field)

| Name | Virtual key |
|------|-------------|
| `Return`, `Enter` | `VK_RETURN` |
| `Escape` | `VK_ESCAPE` |
| `Tab` | `VK_TAB` |
| `Backspace` | `VK_BACK` |
| `Delete` | `VK_DELETE` |
| `Insert` | `VK_INSERT` |
| `Home` | `VK_HOME` |
| `End` | `VK_END` |
| `PageUp` | `VK_PRIOR` |
| `PageDown` | `VK_NEXT` |
| `Left`, `Up`, `Right`, `Down` | Arrow keys |
| `F1` … `F12` | Function keys |

Modifier combinations (e.g. Ctrl+C) are not expressible as a single `key`; use `keys` for literal characters or extend the client in code.

## Client examples

### `rdp_remote`

```bash
rdp_remote command_receive_geometry
rdp_remote command_send_geometry 1920 1080
rdp_remote command_send_geometry
rdp_remote command_send_click 640 400 --button left
rdp_remote command_send_key 'hello'
rdp_remote command_send_key --key Return
rdp_remote --sock-filepath /tmp/rdp.sock command_receive_screenshot --format png
```

Each invocation sends one JSON-line request and prints the full response envelope to stdout. Exit code `0` on success; stderr `error: …` and exit code `1` when the server returns `ok: false` or the socket is unavailable.

### `nc` (one shot)

```bash
printf '%s\n' '{"command":"receive_geometry"}' | nc -U /tmp/rdp.sock
```

### Python

```python
import json
import socket

socket_path = "/tmp/rdp.sock"
request_line = json.dumps({"command": "receive_screenshot", "format": "png"}) + "\n"

client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect(socket_path)
client.sendall(request_line.encode("utf-8"))

response_buffer = b""
while b"\n" not in response_buffer:
    response_buffer += client.recv(4096)

response_body = json.loads(response_buffer.decode("utf-8"))
client.close()

if response_body["ok"]:
    print(response_body["result"]["width"], response_body["result"]["height"])
else:
    print("error:", response_body["error"])
```

### Session workflow

Typical automation loop:

1. Wait for connect (headless: stderr shows `listening on …`).
2. `receive_geometry` — learn coordinate bounds.
3. `receive_screenshot` — capture state (retry if buffer not ready).
4. `send_click` / `send_key` — act on the remote desktop.
5. Repeat until the RDP session ends (socket becomes unavailable or process exits).

## Implementation reference

| Piece | Module |
|-------|--------|
| Socket server, dispatch, envelopes | `src/rdp_pipe/command_socket.py` |
| Command handlers (screenshot, input) | `src/rdp_pipe/rdp_session_core.py` |
| Mouse / keyboard message builders | `src/rdp_pipe/rdp_input.py` |
| CLI `--pipe` / `--headless` wiring | `src/rdp_pipe/entrypoint/rdp.py` |
| Remote command CLI | `src/rdp_pipe/entrypoint/rdp_remote.py` |
| GUI socket startup | `src/rdp_pipe/qt_session_window.py` |

Supported command names are listed in `SUPPORTED_COMMANDS` in `command_socket.py`.
