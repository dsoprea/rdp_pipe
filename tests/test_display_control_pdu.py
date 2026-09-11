"""Unit tests for RDPDISP PDU encoding and caps decoding."""

import struct

import rdp_client.display_control


def test_encode_monitor_layout_pdu_header_and_length():
    """Layout PDU begins with type 2 and monitor count 1."""

    pdu_bytes = rdp_client.display_control.encode_monitor_layout_pdu(1280, 800)

    message_type, monitor_count = struct.unpack("<II", pdu_bytes[0:8])

    assert message_type == rdp_client.display_control.PDU_TYPE_MONITOR_LAYOUT
    assert monitor_count == 1
    assert len(pdu_bytes) == 8 + rdp_client.display_control.MONITOR_LAYOUT_STRUCT_SIZE


def test_encode_monitor_layout_pdu_even_width():
    """Width is forced even per MS-RDPEDISP."""

    pdu_bytes = rdp_client.display_control.encode_monitor_layout_pdu(1281, 800)
    layout_bytes = pdu_bytes[8:]

    flags, left, top, width, height = struct.unpack("<iiiii", layout_bytes[0:20])

    assert flags == rdp_client.display_control.MONITOR_PRIMARY_FLAG
    assert left == 0
    assert top == 0
    assert width == 1280
    assert height == 800


def test_decode_caps_pdu_round_trip_fields():
    """Caps PDU decoder reads monitor limits and area factors."""

    caps_bytes = struct.pack(
        "<IIII",
        rdp_client.display_control.PDU_TYPE_CAPS,
        16,
        8192,
        8192)

    caps = rdp_client.display_control.decode_caps_pdu(caps_bytes)

    assert caps.max_num_monitors == 16
    assert caps.max_monitor_area_factor_a == 8192
    assert caps.max_monitor_area_factor_b == 8192


def test_clamp_even_display_width_bounds():
    """Width clamping enforces minimum, maximum, and even width."""

    assert rdp_client.display_control.clamp_even_display_width(100) == 200
    assert rdp_client.display_control.clamp_even_display_width(9000) == 8192
    assert rdp_client.display_control.clamp_even_display_width(801) == 800
