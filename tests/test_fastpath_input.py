"""Tests for fast-path mouse input PDU construction."""

import aardwolf.commons.queuedata.constants

import rdp_client.fastpath_input


class _FakeCryptoLayer:
    """Minimal cryptolayer stub for PDU layout tests."""

    def __init__(self, use_encrypted_mac: bool):
        self.use_encrypted_mac = use_encrypted_mac
        self.packet_count = 0

    def calc_mac(self, data: bytes) -> bytes:
        return b"\xaa" * 8

    def calc_salted_mac(self, data: bytes, is_server: bool = False) -> bytes:
        return b"\xbb" * 8

    def client_enc(self, data: bytes) -> bytes:
        self.packet_count = self.packet_count + 1

        return data


def test_build_fastpath_mouse_hover_pdu_unencrypted():
    """Unencrypted hover PDU uses one event and MOVE flag."""

    pointer_flags = rdp_client.fastpath_input.build_pointer_flags_for_mouse_button(
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_HOVER,
        False,
        0)

    pdu = rdp_client.fastpath_input.build_fastpath_mouse_input_pdu(
        None,
        pointer_flags,
        662,
        168)

    assert pdu[0] == 0x04
    assert int.from_bytes(pdu[1:3], byteorder="big", signed=False) == 0x800A
    assert pdu[3] == 0x20
    assert int.from_bytes(pdu[4:6], byteorder="little", signed=False) == pointer_flags
    assert int.from_bytes(pdu[6:8], byteorder="little", signed=False) == 662
    assert int.from_bytes(pdu[8:10], byteorder="little", signed=False) == 168


def test_build_fastpath_mouse_hover_pdu_encrypted():
    """Encrypted hover PDU reserves signature bytes before event data."""

    cryptolayer = _FakeCryptoLayer(use_encrypted_mac=False)
    pointer_flags = rdp_client.fastpath_input.build_pointer_flags_for_mouse_button(
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_HOVER,
        False,
        0)

    pdu = rdp_client.fastpath_input.build_fastpath_mouse_input_pdu(
        cryptolayer,
        pointer_flags,
        10,
        20)

    assert pdu[0] == 0x84
    assert int.from_bytes(pdu[1:3], byteorder="big", signed=False) == 0x8012
    assert pdu[3:11] == b"\xaa" * 8
    assert pdu[11] == 0x20
    assert cryptolayer.packet_count == 1
