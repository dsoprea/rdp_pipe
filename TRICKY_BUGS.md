# Tricky bugs

Postmortems for unintuitive defects caused by wire formats, library behavior, or platform defaults — so we do not re-learn them.

## Cursor vanishes over native title bar after leaving canvas

### Symptom

While the remote cursor overlay worked over the session framebuffer, moving the pointer to the **native OS window title bar** (close/minimize chrome above the canvas) made the mouse cursor disappear entirely.

### Root cause

`RdpCanvas` hides the system cursor with **`BlankCursor`** while mirroring the remote pointer. On `leaveEvent` (pointer moves from canvas to WM title bar), the handler called **`unsetCursor()`**. On Linux/Qt, `unsetCursor()` after `BlankCursor` does not reliably restore a visible arrow over window-manager decoration — the same class of failure documented for overlay clears elsewhere in this client.

### Fix

In [`RdpCanvas.leaveEvent`](src/rdp_client/qt_session_window.py), replace `unsetCursor()` with **`setCursor(Qt.ArrowCursor)`** and keep clearing the remote overlay.

### Prevention

- Unit test: `test_leave_event_restores_arrow_cursor_after_blank_cursor` in [`tests/test_qt_session_mouse.py`](tests/test_qt_session_mouse.py).
- When leaving the canvas for non-session chrome, always set an explicit visible cursor shape; do not rely on `unsetCursor()` after `BlankCursor`.

## Double-click opens remote context menu (missing second press / stuck right button)

### Symptom

Double-clicking in the remote desktop sometimes opened a Windows context menu instead of performing the expected double-click action (open file, select word, etc.). Right-click worked when intentional; the failure was intermittent and looked like a left double-click had been reinterpreted as a right-click.

### Root cause

Several stacked input gaps in `RdpCanvas` ([`src/rdp_client/qt_session_window.py`](src/rdp_client/qt_session_window.py)):

1. **No `mouseDoubleClickEvent`** — Qt replaces the second `MouseButtonPress` with `MouseButtonDblClick` on many platforms. We forwarded only press/release handlers, so the remote often saw `LEFT DOWN, LEFT UP, LEFT UP` (orphan release) instead of two full click pairs. RDP has no double-click flag; Windows synthesizes `WM_LBUTTONDBLCLK` only from two complete down/up sequences within the system interval.

2. **Linux right-click release gap** — On Linux, Qt may deliver `QContextMenuEvent` on right-button press without a matching `mouseReleaseEvent`. We forwarded the press (`BUTTON2 DOWN`) but never the release, leaving the server with a stuck right button. Later left clicks or broken double-click timing could then surface as a context menu.

3. **No spurious left→right mapping in code** — `RightButton` only reaches the wire when Qt reports it. Intermittent `RightButton` in traces points at touchpad secondary-click gestures or hardware bounce, not client button remapping.

### Why it was tricky

- Symptom looked like “double-click becomes right-click” but the wire path never mapped `BUTTON1` to `BUTTON2`.
- Hover/pointer work was already correct (`MOUSEBUTTON_HOVER` → `PTRFLAGS.MOVE`), so the bug was isolated to click sequencing, not coordinate mapping.
- Qt’s double-click sequence is four events (`Press, Release, DblClick, Release`), not two; missing the DblClick handler dropped the second down on builds that suppress the second press.

### Journey

1. Confirmed strict button map (`LeftButton` → `MOUSEBUTTON_LEFT`, `RightButton` → `MOUSEBUTTON_RIGHT`) in `_enqueue_mouse_event`.
2. Traced Qt double-click delivery: `MouseButtonDblClick` was ignored entirely.
3. Noted Linux `QContextMenuEvent` is sent on right press even when release is omitted — matches stuck-button hypothesis.
4. Added `RDP_MOUSE_DEBUG=1` tracing before behavior changes to distinguish Qt `RightButton` delivery from server-side stuck state.

### Fix

| Area | Change |
|------|--------|
| Double-click | `mouseDoubleClickEvent` forwards the second press (`is_pressed=True`) using the same button map as `mousePressEvent`. |
| Linux right-click | `setContextMenuPolicy(NoContextMenu)`; `contextMenuEvent` completes the click — sends `BUTTON2 UP` when a right press was already forwarded, otherwise sends full press+release. |
| Event propagation | Mouse/wheel handlers call `accept()` and no longer call `super()` so parent widgets do not reinterpret gestures. |
| Unmapped buttons | `XButton1` / back / forward buttons are ignored with optional debug log instead of `KeyError`. |
| Diagnostics | [`src/rdp_client/mouse_debug.py`](src/rdp_client/mouse_debug.py) — `RDP_MOUSE_DEBUG=1` logs Qt event type, button, buttons, source, remote coordinates, and RDP button state. |

### Prevention

- Run `RDP_MOUSE_DEBUG=1 rdp …` and capture stderr when click behavior misbehaves; look for `RightButton` during a left double-click (input device) vs missing `is_pressed=False` after right press (release gap).
- Unit tests in [`tests/test_qt_session_mouse.py`](tests/test_qt_session_mouse.py) lock the four-event double-click sequence and Linux-style context-menu completion.

### References

- Qt double-click sequence: `Press, Release, DblClick, Release` ([Qt Forum](https://forum.qt.io/topic/90542/click-signal-fired-when-i-double-click-is-this-normal))
- `QContextMenuEvent` on Linux sent on press, independent of mouse event acceptance ([Qt docs](https://doc.qt.io/qt-6/qcontextmenuevent.html))
- MS-RDPBCGR pointer input: no double-click bit; server infers from click pairs

## Window close during connect leaves aardwolf reader tasks pending

### Symptom

Closing the Qt session window — often while the connecting overlay was still up, or while waiting after a dropped session — printed:

```text
Task was destroyed but it is pending!
task: <Task pending name='Task-30' coro=<RDPConnection.__x224_reader() ...>>
Task was destroyed but it is pending!
task: <Task pending name='Task-34' coro=<RDPConnection.__external_reader() ...>>
aardwolf ERROR  Error: Event loop is closed
...
  File ".../asyncio/queues.py", line 188, in get
    getter.cancel()
  File ".../asyncio/base_events.py", line 550, in _check_closed
    raise RuntimeError('Event loop is closed')
```

The CLI had already printed `connecting...`. The process usually still exited, but teardown was noisy and racy.

### Root cause

Several teardown steps stacked:

1. **`RdpSessionWorker.stop()` cancelled `_connection_task`** instead of scheduling `session.stop()`. Cancel during `connect()` raised `CancelledError` before aardwolf’s handshake finished.
2. **`_run_connection`’s `finally` awaited `session.stop()` on an already-cancelled task.** Without `asyncio.shield()`, that await was cancelled again, so `terminate()` often never finished.
3. **aardwolf `terminate()` cancels `__x224_reader` and `__external_reader` but does not await them.** `__x224_reader` is spawned in `__join_channels` (mid-connect). `__external_reader` sits on `ext_in_queue.get()`.
4. **`_async_thread_main` called `loop.close()` immediately** after `run_until_complete`. Python 3.14 `Queue.get()` cleanup then used `loop.call_soon` on a closed loop.

aardwolf `send_disconnect()` can also block on `MCS.out_queue.get()` during an incomplete connect, so the GUI’s 5s join timed out and cancelled from the Qt thread without `call_soon_threadsafe`.

### Why it was tricky

- The traceback lived inside aardwolf and asyncio, so it looked like a library bug rather than our loop-lifetime policy.
- It only appeared sometimes: whether `finally` ran `terminate()` to completion before `loop.close()` was a race.
- “Waiting to reconnect” was the same `connect()` overlay, not a separate reconnect implementation.

### Journey

- Confirmed stderr `connecting...` is printed by the GUI entrypoint before `QApplication.exec()`, so the overlay/connect path is the one that races.
- Read aardwolf `terminate()`: it cancels reader tasks and returns; `__x224_reader`’s `finally` calls `terminate()` again (idempotent via `__terminate_called`).
- Compared with headless `asyncio.run()`, which already drains pending tasks before closing the loop. The GUI worker did not.

### Fix

- Prefer `session.stop()` on the worker loop when a session exists; only cancel `_connection_task` if the session is not created yet.
- `asyncio.shield(self._session.stop())` in `_run_connection` `finally`.
- `close_event_loop_after_cancelling_pending_tasks()` cancels `asyncio.all_tasks()`, gathers them, then `shutdown_asyncgens` / `shutdown_default_executor` before `loop.close()`.
- `RdpDesktopConnection.terminate()` waits up to 2s for aardwolf terminate, closes the transport on timeout, and awaits the name-mangled x224/external reader tasks.
- Shutdown-timeout cancel uses `call_soon_threadsafe`.

### Prevention

- [`tests/test_rdp_session_shutdown.py`](tests/test_rdp_session_shutdown.py) covers loop drain of `Queue.get()` waiters, cooperative `stop()`, thread-safe timeout cancel, awaiting cancelled readers, and disconnect-timeout transport close.
- Do not close a custom asyncio loop until every leftover task has been cancelled and awaited (same contract as `asyncio.run()`).

### References

- Python `asyncio.run()` shutdown: cancel leftover tasks, then close the loop.
- aardwolf `RDPConnection.terminate` / `__x224_reader` / `__external_reader` in `aardwolf/connection.py`.
- [`src/rdp_client/rdp_session_thread.py`](src/rdp_client/rdp_session_thread.py)
- [`src/rdp_client/rdp_connection.py`](src/rdp_client/rdp_connection.py)

## Server drop triggers nested terminate and `await wasn't used with future`

### Symptom

When the RDP server closed the TCP connection (e.g. `BrokenPipeError` while sending mouse input), aardwolf logged a traceback ending in:

```text
RuntimeError: await wasn't used with future
```

at `RdpDesktopConnection._await_cancelled_aardwolf_reader_tasks` while awaiting `__x224_reader_task`.

### Root cause

aardwolf `handle_out_data` calls `await self.terminate()` on write failures. Our `RdpDesktopConnection.terminate()` drains reader tasks after aardwolf `terminate()` cancels them. aardwolf `__x224_reader` also has a `finally: await self.terminate()` — so the nested `terminate()` runs **inside** the x224 reader task and tried to `await` that same task (`asyncio.current_task()`), which raises on Python 3.14.

### Fix

- `terminate()` returns immediately when `_terminate_in_progress` is already set (outer call drains readers).
- `_await_cancelled_aardwolf_reader_tasks()` skips `reader_task is asyncio.current_task()` and consumes finished-task exceptions without awaiting the current task.

### Prevention

- `test_terminate_from_x224_reader_finally_does_not_await_current_task` in [`tests/test_rdp_session_shutdown.py`](tests/test_rdp_session_shutdown.py).

### References

- aardwolf `handle_out_data` except path and `__x224_reader` `finally` in `aardwolf/connection.py`
- [`src/rdp_client/rdp_connection.py`](src/rdp_client/rdp_connection.py) `terminate()` / `_await_cancelled_aardwolf_reader_tasks()`

## Cursor invert pixels lost on some backgrounds (RDP Qt client)

### Symptom

Remote cursor shape and position were correct, but parts of the pointer (I-beam outline, default-arrow XOR regions) were visible on some desktop colors and disappeared on others — e.g. white cursor fragments on white wallpaper.

### Root cause

MS-RDPBCGR **inverted** pointer pixels (monochrome AND=1 XOR=1; color AND=1 with white XOR) must be drawn as **`255 - destination_rgb`** against the live framebuffer. The decoder baked a **static black/white checkerboard** via `_build_inverted_pointer_rgba` and the Qt overlay painted that pixmap with `SourceOver`, so contrast depended on luck, not the desktop under the cursor.

### Fix

- Decode invert bits into a separate **`invert_mask_image`** on `RdpPointerUpdate` (`pointer_update.py`).
- **`RdpRemoteCursorOverlay.paintEvent`** samples the letterboxed canvas `QImage` under each invert pixel and composites with `build_composited_pointer_rgba_image`.
- Repaint the overlay on each video frame when a bitmap pointer is active so inversion tracks desktop updates under a stationary cursor.

### Prevention

- Unit tests: `test_build_pointer_images_marks_monochrome_invert_pixels`, `test_build_composited_pointer_inverts_*_background_*` in `tests/test_pointer_update.py`.
- Do not substitute checkerboard patterns for invert-mask pixels in decode paths.
- 1-bpp AND/XOR bit tests must use `(byte & mask) != 0`, not `>> 7` with a shifting mask — the second bit in a byte was always decoded as 0, garbling I-beam/resize cursors.
- Ignore orphan `PTR_DEFAULT` before any bitmap pointer is cached; keep `BlankCursor` instead of `unsetCursor()` when clearing the overlay so the system busy spinner does not flash.

## Remote cursor shape mirroring (RDP Qt client)

### Symptom

Hovering over UI in an RDP session did not change the local cursor to match the remote desktop. Mouse **position** tracked correctly, but shape stayed on the system arrow.

After implementing fast-path pointer handling and a Qt overlay:

- **I-beam** and other in-content cursors eventually worked (often first as a **solid box** before mask decode fixes).
- **Window-edge resize cursors** (NWSE, NS, EW) never appeared until connect flags were fixed.
- Early sessions showed **I-beam on wallpaper at connect** before hover reached real UI.
- User report “cursor not **chasing**” meant **shape** not position — position forwarding was already correct.

With `RDP_POINTER_DEBUG=1`, healthy resize behavior shows `pointer pdu: 11 kind=bitmap` (or `10` CACHED) on borders. Broken resize showed only `pointer pdu: 6 kind=default` despite correct `mouse hover forwarded remote=(…)` lines.

### Root cause

Several **independent** failures stacked; fixing one layer exposed the next.

| Layer | What was wrong |
|-------|----------------|
| **A — No return path** | aardwolf `_RDPConnection__process_fastpath` handles `BITMAP` video only; pointer PDUs (`COLOR` 9, `POINTER` 11, `CACHED` 10, `PTR_DEFAULT` 6, `PTR_NULL` 5, `LARGE_POINTER` 12) were never forwarded to Qt. |
| **B — Pointer shadows** | With cursor shadows enabled on the Windows session, the server sends bitmap pointers for some shapes (I-beam) but **`PTR_DEFAULT` only** for window resize handles. Fix: set **`PERF.DISABLE_CURSOR_SHADOW`** (`0x20`) in `TS_EXTENDED_INFO_PACKET.performanceFlags`. Distinct from **`DISABLE_CURSORSETTINGS`** (`0x40`, blinking). |
| **C — aardwolf mask swap** | Color-pointer parser reads `xorMaskData` with `lengthAndMask` and vice versa → `index out of range` / truncated XOR for 32×32 cursors. |
| **D — Monochrome beam cursors** | 1-bpp I-beam/resize with every AND byte `0xFF` decode fully transparent without XOR inversion. |
| **E — 24-bpp missing AND** | All-zero AND + black matte → ~90% opaque pixels (`visible_pixels≈898` on 32×32) = solid box. |
| **F — 32-bpp alpha quirk** | Some Windows pointers store opaque RGB with `alpha=0`; needs explicit handling in decode. |
| **G — `PTR_DEFAULT` spam** | Server sends `PTR_DEFAULT` immediately after `POINTER`; applying it clears the overlay. Suppress paired default ~100ms after each bitmap (do **not** drop all `PTR_DEFAULT` forever — busy/wait spinner needs default). |
| **H — Queue / timing** | Pointer PDUs queued behind video (~1000 rects/sec); `run_until_stopped` once checked `.type` before `isinstance(RdpPointerUpdate)` and crashed. Connect-time bitmaps dropped when pointer outside canvas; session-ready reset + synthetic hover added confusion. |
| **I — Qt display** | `setCursor()` on a widget that `setPixmap()` repaints every frame fights the cursor; duplicate `resizeEvent` dropped overlay sizing; wrong “premultiplied” pixmap builder corrupted alpha. |
| **J — 32-bpp connect crash** (separate from cursors but same session path) | `video_bpp_min=32` leaves aardwolf `TS_UD_CS_CORE.colorDepth` as `None` (only 4/8/15/16/24 mapped). CLI default `--color-depth 32` crashed connect; plain `RDPIOSettings` default 16 masked this in smoke tests. Wire `video_bpp_min=24` + `WANT_32BPP_SESSION`. |

### Why it was tricky

1. **One user-visible symptom, many layers** — “cursor wrong” spanned input, fast-path output, decode, Qt, connect flags, and queue ordering.
2. **I-beam worked, resize did not** — looked like edge coordinate mapping; logs showed mapping was correct (`framebuffer=(1280,800)`, `origin=(0,0)`) but server sent only type **6** on borders until shadow flag was set.
3. **aardwolf drops pointers silently** — no error, no hook; required monkey-patching `__process_fastpath` (documented in README monkey-patch table).
4. **Pointer shadow policy is not in MS-RDPBCGR pointer PDU docs** — found via vendor KBs (PAM/Broadcom) and mstsc/FreeRDP `DisableCursorShadow` parity.
5. **Smoke tests lied** — connecting with default 16-bpp iosettings passed while production 32-bpp CLI path crashed.
6. **Misleading debug signatures** — `visible_pixels=920/1024` meant decode bug; `pdu_counts={5:1, 6:12}` with no `10`/`11` meant server policy, not client apply.

### Journey

**Landmarks and dead ends (chronological themes):**

1. **Confirmed hover reaches server** — `MOUSEBUTTON_HOVER` → slow-path `TS_POINTER_EVENT` with `PTRFLAGS.MOVE`; server hit-testing works. Problem was **return path**, not input.
2. **Implemented fast-path pointer handler** — monkey-patch `_RDPConnection__process_fastpath`; bridge via `ext_out_queue` → Qt `pointer_update_ready` (`QueuedConnection`).
3. **32-bpp connect crash** — fixed wire `colorDepth` mapping before cursor work could be tested on real CLI.
4. **aardwolf mask swap** — `fastpath processing failed: index out of range` until `extract_pointer_mask_bytes()` in `pointer_update.py`.
5. **Solid I-beam box** — `xor_bpp=24`, `visible_pixels≈898`; fixed monochrome fixup + 24-bpp matte + 32-bpp alpha paths.
6. **`PTR_DEFAULT` suppression experiments** — ignoring **all** `PTR_DEFAULT` left busy spinner stuck; ignoring **none** wiped I-beam on every move; settled on short suppress after bitmap only.
7. **Video queue starvation** — pointer updates seconds late behind bitmap tiles; immediate dispatch + `drain_queued_pointer_updates()` before `session_ready`.
8. **Connect-time apply** — `pointer apply: bitmap ignored pointer outside canvas` while `pdu_counts` showed `11`/`10`; hydrate from `RdpPointerCache` at session-ready, cache bitmap when outside, removed session-ready synthetic hover.
9. **Qt overlay pivot** — `RdpRemoteCursorOverlay` child widget + `BlankCursor` on canvas; fixed duplicate `resizeEvent`, `PIL.ImageQt` pixmap path, repaint on shape change at last mouse position.
10. **CS_MONITOR GCC injection (reverted)** — injecting `CS_MONITOR` at connect caused “Please wait for Local Session Manager” hang / connection reset. `SUPPORT_MONITOR_LAYOUT_PDU` in core flags is fine; do not inject monitor layout userdata prematurely.
11. **Fast-path mouse input (reverted)** — raw fast-path input PDUs caused connection resets; `fastpath_input.py` kept for future work via aardwolf transport, not raw `writer.write`.
12. **Resize still missing with I-beam OK** — border hovers: only PDU type **6**; **`PERF.DISABLE_CURSOR_SHADOW`** added → resize bitmaps arrived; user confirmed fix.

**Capability / negotiation work (supporting, not sufficient alone):**

- `_patched_pointer_capabilityset_init` — `colorPointerFlag=True`, cache size 25.
- `_augment_client_confirm_active_capabilities` — `LARGE_POINTER` 96×96, `UNICODE`, `MOUSE_HWHEEL`; guard against duplicate `LARGE_POINTER` append.
- Cleared `DISABLE_WALLPAPER` and `DISABLE_CURSORSETTINGS` on performance flags.

**Not pursued / still open:**

- Slow-path `PDUTYPE2_POINTER` (0x1B) — aardwolf does not handle; fast-path sufficed for tested server.
- RDPEMSC `MouseCursor` DVC — newer alternative to legacy pointer PDUs.
- Wire compare with mstsc for remaining edge cases.

### Fix

| Area | Change |
|------|--------|
| Fast-path pointers | `_rdp_desktop_process_fastpath` in `rdp_connection.py` |
| Decode / cache | `pointer_update.py` — masks, beam fixup, 24/32-bpp RGBA, `RdpPointerCache` |
| Qt display | `RdpRemoteCursorOverlay` in `qt_session_window.py` |
| Session bridge | `drain_queued_pointer_updates()`, pointer-before-video in `run_until_stopped` |
| Connect flags | `\| PERF.DISABLE_CURSOR_SHADOW` (resize); wire 24 + `WANT_32BPP_SESSION` (32-bpp sessions) |
| Debug | `RDP_POINTER_DEBUG=1` → `pointer_debug.py` stderr tracing |

Resize fix (key line):

```python
iosettings.performance_flags = (
    iosettings.performance_flags
    & ~PERF.DISABLE_WALLPAPER
    & ~PERF.DISABLE_CURSORSETTINGS
    | PERF.DISABLE_CURSOR_SHADOW)
```

### Prevention

- **`RDP_POINTER_DEBUG=1`** — compare `pointer pdu:` at **window edges** vs **text fields**; edges need types 9–12, not only 6.
- **`pointer session summary`** — `pdu_counts={5:1, 11:1, 10:2, 6:…}` + `pointer cache[0]:` at connect; empty cache + only 5/6 → server not sending bitmaps.
- **`visible_pixels` on bitmap apply** — hundreds on a 32×32 I-beam means decode bug; tens is normal.
- **Connect flags** — parity-check mstsc/FreeRDP (`DisableCursorShadow`, `DisableCursorBlinking`, etc.).
- **Tests** — `tests/test_pointer_update.py`, `tests/test_rdp_connection_factory.py`, `tests/test_qt_session_mapping.py`.
- **Do not** re-enable pointer shadow in remote session UI mid-session.
- **Do not** inject `CS_MONITOR` or raw fast-path input without transport-level validation.
- **Monkey-patches** — update README monkey-patch table when changing aardwolf hooks.

### References

- [MS-RDPBCGR — Pointer Update PDU](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/f68241f5-79bc-4c60-95d6-79ff47e2a302)
- [MS-RDPBCGR — PERF flags (`DISABLE_CURSOR_SHADOW`)](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/732394f5-e2b5-4ac5-8a0a-35345386b0d1)
- [Broadcom KB — resize pointer / pointer shadow](https://knowledge.broadcom.com/external/article/411249/unable-to-resize-windows-in-an-mstsc-rdp.html)
- Code: `rdp_connection.py`, `pointer_update.py`, `qt_session_window.py`, `pointer_debug.py`, `rdp_session_core.py`, `rdp_session_thread.py`
- Reverted experiments: `fastpath_input.py` (do not enable without fixing transport)

## RDPDISP layout applies only once (Deactivate All / Demand Active)

### Symptom

The first `send_geometry` (or first window resize) changed the remote desktop. A second layout request returned success (or appeared to send) but the remote resolution stayed at the first new size. The local canvas stayed pinned at the top-left of a larger window.

### Root cause

Without the graphics pipeline (`egfx`), MS-RDPEDISP applies a monitor layout by running the RDP **deactivation–reactivation** sequence (`Deactivate All` then `Demand Active`, then the client must `Confirm Active` and repeat Synchronize / Control / Font List). aardwolf never reads the MCS share channel after the original connect, so `Demand Active` sat unread on `MCS.out_queue`. The first layout still painted because fast-path bitmaps continued; the server then refused or ignored further layouts while waiting for Confirm Active.

Confirm Active also omitted `TS_BITMAP_CAPABILITYSET.desktopResizeFlag`, so the client advertised that it cannot resize the desktop.

### Why it was tricky

- Qt pixmap / window geometry bugs produce the same “only once / top-left” picture, so those were chased first.
- `send_geometry` returning `ok: true` only means the DVC write succeeded, not that reactivation completed.
- Fast-path video still flows during a half-finished reactivation, so the session looks healthy.

### Fix

- After connect, drain MCS share PDUs and complete reactivation on `Demand Active`.
- Set `desktopResizeFlag=True` on every Confirm Active (initial connect via the handle_out_data augment, and mid-session Confirm Active).
- Clear RDPDISP `channel_id` / caps if the server closes the DVC during reactivation, then open the channel again.

### Prevention

- [`tests/test_rdp_connection_factory.py`](tests/test_rdp_connection_factory.py) asserts `desktopResizeFlag` and Demand Active buffer realloc.
- After the first `send_geometry`, a second different size must change both `receive_geometry` and the painted desktop.

### References

- [MS-RDPBCGR deactivation-reactivation](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/dfc234ce-481a-4306-9e45-0e9a5e4e6c82)
- [MS-RDPEDISP monitor layout](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpedisp/22741217-12a0-4fb8-b5a0-df43905aaf06)
- [`src/rdp_client/rdp_connection.py`](src/rdp_client/rdp_connection.py) — `_run_share_channel_loop`, `_complete_deactivation_reactivation`

## Command pipe fails with “event loop is not running”

### Symptom

`rdp --pipe` creates `/tmp/rdp.sock`, but `socat` / `nc` commands hang, time out, or return  
`{"ok":false,"error":"RDP session event loop is not running"}`.

### Root cause

`CommandSocketServer` runs on a background thread and marshals commands with `asyncio.run_coroutine_threadsafe` onto the session loop. `RdpAsyncSession.event_loop` used `asyncio.get_running_loop()`, which only works **inside** a running coroutine on that loop — not from the command-socket thread. The property always returned `None` there.

### Fix

Capture the loop at the start of `RdpAsyncSession.connect()` (`self._event_loop = asyncio.get_running_loop()`) and return that stored reference from the `event_loop` property.

### Prevention

- [`tests/test_command_socket.py`](tests/test_command_socket.py) dispatches a command via `asyncio.to_thread` while the session loop is running.
- Any cross-thread asyncio bridge must hold an explicit loop reference, not call `get_running_loop()` from the foreign thread.

## QLabel setPixmap raises minimum size and blocks repeat RDPDISP resize

### Symptom

Seamless resize (MS-RDPEDISP) worked once after connect; dragging the client window again did not change remote resolution. Resize cursors on window edges stopped updating after the first resize.

### Root cause

`RdpCanvas` is a `QLabel` that calls `setPixmap()` with a pixmap sized to the remote framebuffer. Qt raises the label's **minimum size hint** to the pixmap dimensions. The parent `RdpSessionContainer` fills the canvas with `setGeometry(container_rectangle)`, but `QWidget::setGeometry` honors `minimumSize()` — after the first RDPDISP cycle the canvas could not shrink (and sometimes stopped tracking the window). `RdpCanvas.resizeEvent` no longer fired on later window drags, so debounced RDPDISP requests stopped.

### Why it was tricky

- First resize often **grows** the window, so minimum-size clamping is invisible.
- The failure is in Qt layout constraints, not in RDPDISP PDU encoding or aardwolf.
- Letterbox / edge-hover symptoms look like pointer or mapping bugs but stem from stale geometry.

### Fix

- `RdpCanvas` is a `QWidget` that paints a `QImage` in `paintEvent` — do **not** use `QLabel.setPixmap()` for the framebuffer; pixmap size hints still constrain the main window even with `setMinimumSize(0, 0)`.
- `RdpCanvas`: `setMinimumSize(0, 0)` and `QSizePolicy.Ignored`; `RdpSessionContainer` and `RdpSessionWindow` also use zero minimum / ignored size policy.
- Move RDPDISP debounce to `RdpSessionContainer.resizeEvent` using the **container** client area size.
- Do **not** record “last requested resolution” in the Qt layer before the RDPDISP PDU is sent — pre-connect debounces and failed sends poisoned dedup and blocked later resizes. Track last-sent size only in `DisplayControlChannel.request_resolution` after `channel_data_out` succeeds.
- Gate resize requests until `session_ready` (RDPDISP caps are negotiated during connect). Dedup only in `DisplayControlChannel.request_resolution` (`_last_sent_width` / `_last_sent_height`) after a successful `channel_data_out` — do not compare client size to `session.iosettings` in Qt and do not seed `record_sent_resolution` with the negotiated connect size (that blocks the first real layout PDU when the container already matches).
- Forward every debounced container resize after `session_ready`; the display channel skips identical consecutive layouts.
- Map mouse input with authoritative `_remote_width` / `_remote_height` (`qt_session_mapping.py`), not `pixmap.width()` / `pixmap.height()` while the pixmap lags the session after RDPDISP.
- After geometry changes, re-forward hover at the last pointer position (`sync_pointer_after_geometry_change`) so server hit-testing and the cursor overlay stay aligned.

### Prevention

- [`tests/test_qt_session_geometry.py`](tests/test_qt_session_geometry.py) asserts the canvas shrinks after `setPixmap` when minimum size is zero.
- [`tests/test_display_control_pdu.py`](tests/test_display_control_pdu.py) asserts duplicate layout PDUs are not retransmitted.
- [`tests/test_qt_session_mapping.py`](tests/test_qt_session_mapping.py) covers letterbox mapping against session dimensions.
- When using `QLabel` as a framebuffer surface, never rely on implicit minimum size from pixmap content.

### References

- [`src/rdp_client/qt_session_window.py`](src/rdp_client/qt_session_window.py) — `RdpCanvas`, `RdpSessionContainer`
- [`src/rdp_client/qt_session_mapping.py`](src/rdp_client/qt_session_mapping.py) — shared coordinate mapping
- [`src/rdp_client/display_control.py`](src/rdp_client/display_control.py) — last-sent layout dedup
- Qt `QLabel::minimumSizeHint()` — returns pixmap size when a pixmap is set
