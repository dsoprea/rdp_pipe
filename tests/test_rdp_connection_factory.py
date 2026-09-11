"""Unit tests for RdpDesktopConnectionFactory iosettings handling."""

import aardwolf.protocol.T125.extendedinfopacket
import aardwolf.protocol.pdu.capabilities
import aardwolf.protocol.pdu.capabilities.input
import aardwolf.protocol.pdu.capabilities.largepointer
import aardwolf.protocol.pdu.capabilities.pointer
import aardwolf.protocol.T128.clientconfirmactivepdu

import rdp_client.display_control
import rdp_client.rdp_connection


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

    rdp_client.rdp_connection._augment_client_confirm_active_capabilities(confirm_active_pdu)

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


def test_build_iosettings_does_not_disable_wallpaper():
    """Client must not ask the server to omit the desktop wallpaper."""

    iosettings, _display_control_channel = \
        rdp_client.rdp_connection.build_iosettings_with_display_control(
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
        rdp_client.rdp_connection.build_iosettings_with_display_control(
            1280,
            800,
            color_depth=16)

    assert iosettings.video_bpp_max == 16
    assert iosettings.video_bpp_min == 16


def test_build_iosettings_maps_32bpp_wire_color_depth():
    """32-bpp sessions use 24 on the wire for aardwolf Client Core colorDepth fields."""

    iosettings, _display_control_channel = \
        rdp_client.rdp_connection.build_iosettings_with_display_control(
            1280,
            800,
            color_depth=32)

    assert iosettings.video_bpp_max == 32
    assert iosettings.video_bpp_min == 24


def test_get_connection_preserves_display_control_channel_identity():
    """Virtual channel instances in vchannels must not be duplicated by deepcopy."""

    iosettings, display_control_channel = \
        rdp_client.rdp_connection.build_iosettings_with_display_control(
            1280,
            800)

    connection_url = \
        "rdp+ntlm-password://Administrator:placeholder@10.0.0.5"

    connection_factory = \
        rdp_client.rdp_connection.RdpDesktopConnectionFactory.from_url(
            connection_url,
            iosettings)

    connection = connection_factory.get_connection(iosettings)

    live_display_control_channel = connection.iosettings.vchannels[
        rdp_client.display_control.DISPLAY_CONTROL_CHANNEL_NAME]

    assert live_display_control_channel is display_control_channel
