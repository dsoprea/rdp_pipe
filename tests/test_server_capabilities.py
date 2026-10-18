"""Unit tests for post-connect server capability stderr reporting."""

import types

import aardwolf.protocol.T124.userdata
import aardwolf.protocol.T124.userdata.constants
import aardwolf.protocol.T124.userdata.servercoredata
import aardwolf.protocol.pdu.capabilities
import aardwolf.protocol.pdu.capabilities.bitmap
import aardwolf.protocol.pdu.capabilities.general
import aardwolf.protocol.T128.serverdemandactivepdu

import rdp_pipe.display_control
import rdp_pipe.server_capabilities


def test_build_server_capability_report_includes_gcc_demand_active_and_rdpdisp():
    """Report lists GCC userdata, Demand Active sets, and RDPDISP caps."""

    server_core = aardwolf.protocol.T124.userdata.servercoredata.TS_UD_SC_CORE()
    server_core.version = 0x00080004
    server_core.clientRequestedProtocols = 3
    server_core.earlyCapabilityFlags = \
        aardwolf.protocol.T124.userdata.constants.RNS_UD_SC.DYNAMIC_DST_SUPPORTED

    server_connect_pdu = aardwolf.protocol.T124.userdata.TS_SC()
    server_connect_pdu.serverdata[
        aardwolf.protocol.T124.userdata.constants.TS_UD_TYPE.SC_CORE] = server_core

    general_capability = \
        aardwolf.protocol.pdu.capabilities.general.TS_GENERAL_CAPABILITYSET()
    general_capability.osMajorType = \
        aardwolf.protocol.pdu.capabilities.general.OSMAJORTYPE.WINDOWS
    general_capability.osMinorType = \
        aardwolf.protocol.pdu.capabilities.general.OSMINORTYPE.WINDOWS_NT

    bitmap_capability = aardwolf.protocol.pdu.capabilities.bitmap.TS_BITMAP_CAPABILITYSET()
    bitmap_capability.desktopWidth = 1920
    bitmap_capability.desktopHeight = 1080
    bitmap_capability.preferredBitsPerPixel = 32

    demand_active_pdu = aardwolf.protocol.T128.serverdemandactivepdu.TS_DEMAND_ACTIVE_PDU()
    demand_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(general_capability))
    demand_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(bitmap_capability))

    display_control_channel = rdp_pipe.display_control.DisplayControlChannel()
    display_control_channel._caps = rdp_pipe.display_control.DisplayControlCaps(
        16,
        8192,
        8192)

    connection = type(
        "StubConnection",
        (),
        {
            "_RDPConnection__server_connect_pdu": server_connect_pdu,
            "_server_demand_active_pdu": demand_active_pdu,
            "display_control_channel": display_control_channel,
        })()

    report_lines = rdp_pipe.server_capabilities.build_server_capability_report_lines(
        connection)
    report_text = "\n".join(report_lines)

    assert "Server capabilities:" in report_text
    assert "Connect GCC server data:" in report_text
    assert "SC_CORE" in report_text
    assert "Demand Active capability sets:" in report_text
    assert "GENERAL" in report_text
    assert "BITMAP" in report_text
    assert "desktopWidth: 1920" in report_text
    assert "RDPDISP display control:" in report_text
    assert "max_num_monitors: 16" in report_text


def test_demand_active_from_bytes_patch_stores_pdu_on_connecting_desktop_connection(
        monkeypatch):
    """Demand Active parsing during connect retains the server PDU on the connection."""

    import rdp_pipe.rdp_connection

    demand_active_pdu = aardwolf.protocol.T128.serverdemandactivepdu.TS_DEMAND_ACTIVE_PDU()
    demand_active_pdu.capabilitySets.append(
        aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(
            aardwolf.protocol.pdu.capabilities.bitmap.TS_BITMAP_CAPABILITYSET()))

    def fake_demand_active_from_bytes(_payload_bytes):
        return demand_active_pdu

    monkeypatch.setattr(
        rdp_pipe.rdp_connection,
        "_ORIGINAL_DEMAND_ACTIVE_FROM_BYTES",
        fake_demand_active_from_bytes)

    connection = types.SimpleNamespace(_server_demand_active_pdu=None)

    rdp_pipe.rdp_connection._CONNECTING_DESKTOP_CONNECTION = connection

    try:
        aardwolf.protocol.T128.serverdemandactivepdu.TS_DEMAND_ACTIVE_PDU.from_bytes(
            b"\x00")

    finally:
        rdp_pipe.rdp_connection._CONNECTING_DESKTOP_CONNECTION = None

    assert connection._server_demand_active_pdu is demand_active_pdu
    assert len(connection._server_demand_active_pdu.capabilitySets) == 1
