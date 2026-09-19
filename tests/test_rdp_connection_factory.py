"""Unit tests for RdpDesktopConnectionFactory iosettings handling."""

import asyncio
import unittest.mock

import aardwolf.protocol.T125.extendedinfopacket
import aardwolf.protocol.pdu.capabilities
import aardwolf.protocol.pdu.capabilities.bitmap
import aardwolf.protocol.pdu.capabilities.input
import aardwolf.protocol.pdu.capabilities.largepointer
import aardwolf.protocol.pdu.capabilities.pointer
import aardwolf.protocol.T128.clientconfirmactivepdu
import aardwolf.protocol.T128.serverdemandactivepdu
import aardwolf.protocol.T128.share

import rdp_pipe.display_control
import rdp_pipe.rdp_connection


def test_pointer_capabilityset_advertises_color_and_cache_sizes():
    """Client pointer caps match mstsc-style cache sizes and color pointers."""

    pointer_capability = aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET()

    assert pointer_capability.colorPointerFlag is True
    assert pointer_capability.colorPointerCacheSize == 25
    assert pointer_capability.pointerCacheSize == 25


def test_augment_client_confirm_active_capabilities_adds_large_pointer_and_input_flags():
    """Confirm Active gains large-pointer support and full input flags."""

    confirm_active_pdu = aardwolf.protocol.T128.clientconfirmactivepdu.TS_CONFIRM_ACTIVE_PDU()
    confirm_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(
            aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET()))
    confirm_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(
            aardwolf.protocol.pdu.capabilities.input.TS_INPUT_CAPABILITYSET()))

    rdp_pipe.rdp_connection._augment_client_confirm_active_capabilities(confirm_active_pdu)

    capability_types = [
        capability_set.capabilitySetType
        for capability_set in confirm_active_pdu.capabilitySets]

    assert aardwolf.protocol.pdu.capabilities.CAPSTYPE.LARGE_POINTER in capability_types

    input_capability = None

    for capability_set in confirm_active_pdu.capabilitySets:
        if capability_set.capabilitySetType == aardwolf.protocol.pdu.capabilities.CAPSTYPE.INPUT:
            input_capability = capability_set.capability

    assert input_capability is not None
    assert aardwolf.protocol.pdu.capabilities.input.INPUT_FLAG.UNICODE in input_capability.inputFlags
    assert aardwolf.protocol.pdu.capabilities.input.INPUT_FLAG.MOUSE_HWHEEL \
        in input_capability.inputFlags
    assert aardwolf.protocol.pdu.capabilities.input.INPUT_FLAG.FASTPATH_INPUT2 \
        not in input_capability.inputFlags


def test_augment_client_confirm_active_sets_desktop_resize_flag():
    """Bitmap caps must advertise desktopResizeFlag so later RDPDISP layouts apply."""

    confirm_active_pdu = aardwolf.protocol.T128.clientconfirmactivepdu.TS_CONFIRM_ACTIVE_PDU()
    bitmap_capability = aardwolf.protocol.pdu.capabilities.bitmap.TS_BITMAP_CAPABILITYSET()
    bitmap_capability.preferredBitsPerPixel = 24
    bitmap_capability.desktopWidth = 1280
    bitmap_capability.desktopHeight = 800
    confirm_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(bitmap_capability))
    confirm_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(
            aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET()))
    confirm_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(
            aardwolf.protocol.pdu.capabilities.input.TS_INPUT_CAPABILITYSET()))

    rdp_pipe.rdp_connection._augment_client_confirm_active_capabilities(confirm_active_pdu)

    resized_bitmap_capability = None

    for capability_set in confirm_active_pdu.capabilitySets:
        if capability_set.capabilitySetType == aardwolf.protocol.pdu.capabilities.CAPSTYPE.BITMAP:
            resized_bitmap_capability = capability_set.capability

    assert resized_bitmap_capability is not None
    assert resized_bitmap_capability.desktopResizeFlag is True


def test_apply_demand_active_desktop_size_reallocates_when_server_size_differs():
    """Demand Active bitmap caps drive a local framebuffer realloc after layout."""

    connection = unittest.mock.Mock()
    connection.iosettings = unittest.mock.Mock()
    connection.iosettings.video_width = 1280
    connection.iosettings.video_height = 800
    connection.reallocate_desktop_buffer = unittest.mock.Mock()

    bitmap_capability = aardwolf.protocol.pdu.capabilities.bitmap.TS_BITMAP_CAPABILITYSET()
    bitmap_capability.desktopWidth = 1600
    bitmap_capability.desktopHeight = 900
    bitmap_capability_set = unittest.mock.Mock()
    bitmap_capability_set.capabilitySetType = aardwolf.protocol.pdu.capabilities.CAPSTYPE.BITMAP
    bitmap_capability_set.capability = bitmap_capability
    demand_active = unittest.mock.Mock()
    demand_active.capabilitySets = [bitmap_capability_set]

    rdp_pipe.rdp_connection.RdpDesktopConnection._apply_demand_active_desktop_size(
        connection,
        demand_active)

    connection.reallocate_desktop_buffer.assert_called_once_with(1600, 900)


def test_build_iosettings_does_not_disable_wallpaper():
    """Client must not ask the server to omit the desktop wallpaper."""

    iosettings, _display_control_channel = \
        rdp_pipe.rdp_connection.build_iosettings_with_display_control(
            1280,
            800)

    disable_wallpaper_flag = \
        aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_WALLPAPER

    assert (iosettings.performance_flags & disable_wallpaper_flag) == 0

    disable_cursor_settings_flag = \
        aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_CURSORSETTINGS

    assert (iosettings.performance_flags & disable_cursor_settings_flag) == 0

    disable_cursor_shadow_flag = \
        aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_CURSOR_SHADOW

    assert (iosettings.performance_flags & disable_cursor_shadow_flag) != 0


def test_build_iosettings_honors_color_depth():
    """video_bpp_max and video_bpp_min match the requested color depth."""

    iosettings, _display_control_channel = \
        rdp_pipe.rdp_connection.build_iosettings_with_display_control(
            1280,
            800,
            color_depth=16)

    assert iosettings.video_bpp_max == 16
    assert iosettings.video_bpp_min == 16


def test_build_iosettings_maps_32bpp_wire_color_depth():
    """32-bpp sessions use 24 on the wire for aardwolf Client Core colorDepth fields."""

    iosettings, _display_control_channel = \
        rdp_pipe.rdp_connection.build_iosettings_with_display_control(
            1280,
            800,
            color_depth=32)

    assert iosettings.video_bpp_max == 32
    assert iosettings.video_bpp_min == 24


def test_get_connection_preserves_display_control_channel_identity():
    """Virtual channel instances in vchannels must not be duplicated by deepcopy."""

    iosettings, display_control_channel = \
        rdp_pipe.rdp_connection.build_iosettings_with_display_control(
            1280,
            800)

    connection_url = \
        "rdp+ntlm-password://Administrator:placeholder@10.0.0.5"

    connection_factory = \
        rdp_pipe.rdp_connection.RdpDesktopConnectionFactory.from_url(
            connection_url,
            iosettings)

    connection = connection_factory.get_connection(iosettings)

    live_display_control_channel = connection.iosettings.vchannels[
        rdp_pipe.display_control.DISPLAY_CONTROL_CHANNEL_NAME]

    assert live_display_control_channel is display_control_channel


def _build_share_control_header_bytes(pdu_type):
    """Encode a 6-byte TS_SHARECONTROLHEADER for share-channel loop tests."""

    header = aardwolf.protocol.T128.share.TS_SHARECONTROLHEADER()
    header.totalLength = 6
    header.pduType = pdu_type
    header.pduVersion = 1
    header.pduSource = 1002

    return header.to_bytes()


async def _collect_share_loop_reactivation_payloads():
    """Run the MCS drain loop until a queued error stops it; return Demand Active payloads."""

    # Feed leftover Font Map-style data, then Demand Active, then a stop error.

    out_queue = asyncio.Queue()
    mcs_channel = unittest.mock.Mock()
    mcs_channel.out_queue = out_queue
    connection = unittest.mock.Mock()
    connection._RDPConnection__joined_channels = {"MCS": mcs_channel}
    connection._get_capability_exchange_data_start_offset = unittest.mock.Mock(return_value=0)
    connection._complete_deactivation_reactivation = unittest.mock.AsyncMock()

    leftover_bytes = _build_share_control_header_bytes(
        aardwolf.protocol.T128.share.PDUTYPE.DATAPDU)
    demand_active_bytes = _build_share_control_header_bytes(
        aardwolf.protocol.T128.share.PDUTYPE.DEMANDACTIVEPDU)

    await out_queue.put((leftover_bytes, None))
    await out_queue.put((demand_active_bytes, None))
    await out_queue.put((None, RuntimeError("stop share loop")))

    await rdp_pipe.rdp_connection.RdpDesktopConnection._run_share_channel_loop(
        connection)

    return connection._complete_deactivation_reactivation.await_args_list


def test_share_channel_loop_completes_reactivation_on_demand_active():
    """Leftover share data PDUs are skipped; Demand Active is answered."""

    await_args_list = asyncio.run(_collect_share_loop_reactivation_payloads())

    assert len(await_args_list) == 1
    demand_active_bytes = _build_share_control_header_bytes(
        aardwolf.protocol.T128.share.PDUTYPE.DEMANDACTIVEPDU)

    assert await_args_list[0].args[0] == demand_active_bytes


async def _run_complete_deactivation_reactivation_with_caps_already_received():
    """Drive reactivation when RDPDISP caps survived the layout sequence."""

    # Stub the post-Confirm-Active handshake; caps already present so skip wait_for_caps.

    connection = unittest.mock.Mock()
    connection._apply_demand_active_desktop_size = unittest.mock.Mock()
    connection._send_client_confirm_active = unittest.mock.AsyncMock()
    connection._get_capability_exchange_data_start_offset = unittest.mock.Mock(return_value=0)
    connection._await_synchronize_after_confirm_active = unittest.mock.AsyncMock()
    connection._finish_mandatory_capability_exchange_after_synchronize = \
        unittest.mock.AsyncMock()
    connection.open_display_control_channel = unittest.mock.AsyncMock()
    connection._release_keyboard_modifiers_after_reactivation = unittest.mock.AsyncMock()
    connection.display_control_channel = unittest.mock.Mock()
    connection.display_control_channel.caps_received = True
    connection.display_control_channel.wait_for_caps = unittest.mock.AsyncMock()
    demand_active = unittest.mock.Mock()

    with unittest.mock.patch.object(
            aardwolf.protocol.T128.serverdemandactivepdu.TS_DEMAND_ACTIVE_PDU,
            "from_bytes",
            return_value=demand_active):

        await rdp_pipe.rdp_connection.RdpDesktopConnection._complete_deactivation_reactivation(
            connection,
            b"demand-active")

    return connection, demand_active


def test_complete_deactivation_reactivation_confirms_active_and_reopens_display_control():
    """Demand Active must Confirm Active, finish capability exchange, and reopen RDPDISP."""

    connection, demand_active = \
        asyncio.run(_run_complete_deactivation_reactivation_with_caps_already_received())

    connection._apply_demand_active_desktop_size.assert_called_once_with(demand_active)
    connection._send_client_confirm_active.assert_awaited_once()
    connection._await_synchronize_after_confirm_active.assert_awaited_once_with(0)
    connection._finish_mandatory_capability_exchange_after_synchronize.assert_awaited_once()
    connection.open_display_control_channel.assert_awaited_once()
    connection._release_keyboard_modifiers_after_reactivation.assert_awaited_once()
    connection.display_control_channel.wait_for_caps.assert_not_awaited()

