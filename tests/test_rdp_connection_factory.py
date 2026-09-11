"""Unit tests for RdpDesktopConnectionFactory iosettings handling."""

import rdp_client.display_control
import rdp_client.rdp_connection


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
