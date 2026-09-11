"""Unit tests for RdpDesktopConnectionFactory iosettings handling."""

import aardwolf.protocol.T125.extendedinfopacket

import rdp_client.display_control
import rdp_client.rdp_connection


def test_build_iosettings_does_not_disable_wallpaper():
    """Client must not ask the server to omit the desktop wallpaper."""

    iosettings, _display_control_channel = \
        rdp_client.rdp_connection.build_iosettings_with_display_control(
            1280,
            800)

    disable_wallpaper_flag = \
        aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_WALLPAPER

    assert (iosettings.performance_flags & disable_wallpaper_flag) == 0


def test_build_iosettings_honors_color_depth():
    """video_bpp_max and video_bpp_min match the requested color depth."""

    iosettings, _display_control_channel = \
        rdp_client.rdp_connection.build_iosettings_with_display_control(
            1280,
            800,
            color_depth=16)

    assert iosettings.video_bpp_max == 16
    assert iosettings.video_bpp_min == 16


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
