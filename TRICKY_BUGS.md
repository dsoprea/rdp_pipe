# Tricky bugs

Postmortems for unintuitive defects caused by wire formats, library behavior, or platform defaults — so we do not re-learn them.

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
