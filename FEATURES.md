# Features

## CLI (`rdp_connect`)

- Positional RDP URL (aardwolf `rdp+ntlm-password://` form or bare host normalized to that scheme)
- Password from URL userinfo, `RDP_PASSWORD`, or stdin (`getpass` on a TTY; one line when piped)
- Exits non-zero with a clear stderr message when password resolution fails

## Desktop session (PyQt6)

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

## Authentication scope

- NLA / CredSSP with NTLM password URLs (`rdp+ntlm-password://`)
- Windows RDP targets with NLA enabled

## Known limitations

- RDPDISP requires server support; older or non-Windows RDP stacks may not resize remotely
- Clipboard, multi-monitor, drive redirection, and RemoteApp (RAIL) are not implemented
- aardwolf bitmap rendering path only; modern GFX/H.264 remoting may not apply
