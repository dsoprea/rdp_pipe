"""Unit tests for RDPDISP PDU encoding and caps decoding."""

import asyncio
import struct

import rdp_client.display_control


def test_encode_monitor_layout_pdu_header_and_length():
    """Layout PDU begins with type 2 and monitor count 1."""

    pdu_bytes = rdp_client.display_control.encode_monitor_layout_pdu(1280, 800)

    message_type, pdu_length, monitor_layout_size, monitor_count = struct.unpack(
        "<IIII",
        pdu_bytes[0:16])

    assert message_type == rdp_client.display_control.PDU_TYPE_MONITOR_LAYOUT
    assert pdu_length == 16 + rdp_client.display_control.MONITOR_LAYOUT_STRUCT_SIZE
    assert monitor_layout_size == rdp_client.display_control.MONITOR_LAYOUT_STRUCT_SIZE
    assert monitor_count == 1
    assert len(pdu_bytes) == 16 + rdp_client.display_control.MONITOR_LAYOUT_STRUCT_SIZE


def test_encode_monitor_layout_pdu_even_width():
    """Width is forced even per MS-RDPEDISP."""

    pdu_bytes = rdp_client.display_control.encode_monitor_layout_pdu(1281, 800)
    layout_bytes = pdu_bytes[16:]

    flags, left, top, width, height = struct.unpack("<iiiii", layout_bytes[0:20])

    assert flags == rdp_client.display_control.MONITOR_PRIMARY_FLAG
    assert left == 0
    assert top == 0
    assert width == 1280
    assert height == 800


def test_decode_caps_pdu_round_trip_fields():
    """Caps PDU decoder reads monitor limits and area factors."""

    caps_bytes = struct.pack(
        "<IIIII",
        rdp_client.display_control.PDU_TYPE_CAPS,
        20,
        16,
        8192,
        8192)

    caps = rdp_client.display_control.decode_caps_pdu(caps_bytes)

    assert caps.max_num_monitors == 16
    assert caps.max_monitor_area_factor_a == 8192
    assert caps.max_monitor_area_factor_b == 8192


def test_record_sent_resolution_skips_initial_duplicate_layout_pdu():
    """Negotiated connect size can be marked sent without a wire PDU."""

    async def run_recorded_resolution_requests():
        channel = rdp_client.display_control.DisplayControlChannel()
        channel._caps = rdp_client.display_control.DisplayControlCaps(1, 8192, 8192)
        transmit_count = 0

        async def count_channel_data_out(pdu_bytes: bytes):
            nonlocal transmit_count
            transmit_count = transmit_count + 1

        channel.channel_data_out = count_channel_data_out
        channel.record_sent_resolution(1280, 800)

        accepted = await channel.request_resolution(1280, 800)

        return accepted, transmit_count

    accepted, transmit_count = asyncio.run(run_recorded_resolution_requests())

    assert accepted is True
    assert transmit_count == 0


def test_request_resolution_skips_duplicate_layout_pdu():
    """Identical clamped layouts are not transmitted twice in a row."""

    async def run_duplicate_resolution_requests():
        channel = rdp_client.display_control.DisplayControlChannel()
        channel._caps = rdp_client.display_control.DisplayControlCaps(1, 8192, 8192)
        transmit_count = 0

        async def count_channel_data_out(pdu_bytes: bytes):
            nonlocal transmit_count
            transmit_count = transmit_count + 1

        channel.channel_data_out = count_channel_data_out

        first_accepted = await channel.request_resolution(1280, 800)
        second_accepted = await channel.request_resolution(1280, 800)
        third_accepted = await channel.request_resolution(1400, 800)

        return first_accepted, second_accepted, third_accepted, transmit_count

    first_accepted, second_accepted, third_accepted, transmit_count = \
        asyncio.run(run_duplicate_resolution_requests())

    assert first_accepted is True
    assert second_accepted is True
    assert third_accepted is True
    assert transmit_count == 2


def test_clamp_even_display_width_bounds():
    """Width clamping enforces minimum, maximum, and even width."""

    assert rdp_client.display_control.clamp_even_display_width(100) == 200
    assert rdp_client.display_control.clamp_even_display_width(9000) == 8192
    assert rdp_client.display_control.clamp_even_display_width(801) == 800


def test_channel_closed_clears_caps_and_channel_id():
    """Server DVC close during reactivation must not leave a stale channel id."""

    async def run_channel_closed():
        channel = rdp_client.display_control.DisplayControlChannel()
        channel.channel_id = 7
        channel._caps = rdp_client.display_control.DisplayControlCaps(1, 8192, 8192)
        channel._caps_received_event.set()
        channel._last_sent_width = 1600
        channel._last_sent_height = 900

        await channel.channel_closed()

        return channel.channel_id, channel.caps_received, channel._last_sent_width

    channel_id, caps_received, last_sent_width = asyncio.run(run_channel_closed())

    assert channel_id is None
    assert caps_received is False
    assert last_sent_width is None
