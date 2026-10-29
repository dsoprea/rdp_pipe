"""Unit tests for RDP connection heartbeat probes."""

import asyncio
import unittest.mock

import aardwolf.protocol.T128.security

import rdp_pipe.connection_heartbeat


def test_build_ts_heartbeat_pdu_default_period():
    """Default heartbeat advertises a 15-second period on the wire."""

    heartbeat_pdu = rdp_pipe.connection_heartbeat.build_ts_heartbeat_pdu()

    assert heartbeat_pdu.to_bytes() == bytes([0, 15, 1, 2])


async def _run_send_connection_heartbeat_with_mock_channel():
    """Exercise send_connection_heartbeat with a fake MCS channel."""

    message_channel = unittest.mock.Mock()
    message_channel.channel_id = 1003
    connection = unittest.mock.Mock()
    connection._RDPConnection__joined_channels = {"MCS": message_channel}
    connection.cryptolayer = object()
    connection.handle_out_data = unittest.mock.AsyncMock(return_value=(True, None))

    send_ok, send_error = await rdp_pipe.connection_heartbeat.send_connection_heartbeat(
        connection)

    return send_ok, send_error, connection.handle_out_data


def test_send_connection_heartbeat_uses_mcs_message_channel():
    """Heartbeat is sent on the MCS channel with HEARTBEAT and ENCRYPT flags."""

    send_ok, send_error, handle_out_data = asyncio.run(
        _run_send_connection_heartbeat_with_mock_channel())

    assert send_ok is True
    assert send_error is None
    handle_out_data.assert_awaited_once()
    call_arguments = handle_out_data.await_args
    heartbeat_pdu = call_arguments.args[0]
    security_header = call_arguments.args[1]
    channel_identifier = call_arguments.args[4]

    assert heartbeat_pdu.to_bytes() == bytes([0, 15, 1, 2])
    assert security_header.flags & aardwolf.protocol.T128.security.SEC_HDR_FLAG.HEARTBEAT
    assert security_header.flags & aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT
    assert channel_identifier == 1003


async def _run_send_connection_heartbeat_without_mcs():
    """Return early when MCS is not joined yet."""

    connection = unittest.mock.Mock()
    connection._RDPConnection__joined_channels = {}

    return await rdp_pipe.connection_heartbeat.send_connection_heartbeat(connection)


def test_send_connection_heartbeat_skips_when_mcs_missing():
    """Mid-connect sessions must not attempt heartbeat sends."""

    send_ok, send_error = asyncio.run(_run_send_connection_heartbeat_without_mcs())

    assert send_ok is False
    assert send_error is None
