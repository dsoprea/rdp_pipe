"""Unit tests for TCP keepalive on the RDP transport."""

import socket
import unittest.mock

import rdp_pipe.connection_heartbeat


def test_enable_tcp_keepalive_sets_linux_probe_options():
    """Keepalive uses 15-second idle and interval when TCP_* options exist."""

    socket_object = unittest.mock.Mock()
    transport_connection = unittest.mock.Mock()
    transport_connection.get_extra_info = unittest.mock.Mock(return_value=socket_object)
    connection = unittest.mock.Mock()
    connection._RDPConnection__connection = transport_connection

    enabled = rdp_pipe.connection_heartbeat.enable_tcp_keepalive_on_connection(connection)

    assert enabled is True
    socket_object.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    if hasattr(socket, "TCP_KEEPIDLE"):
        socket_object.setsockopt.assert_any_call(
            socket.IPPROTO_TCP,
            socket.TCP_KEEPIDLE,
            rdp_pipe.connection_heartbeat.CONNECTION_KEEPALIVE_IDLE_SECONDS)

    if hasattr(socket, "TCP_KEEPINTVL"):
        socket_object.setsockopt.assert_any_call(
            socket.IPPROTO_TCP,
            socket.TCP_KEEPINTVL,
            rdp_pipe.connection_heartbeat.CONNECTION_KEEPALIVE_INTERVAL_SECONDS)


def test_enable_tcp_keepalive_returns_false_without_transport():
    """Mid-connect shells without a transport must not raise."""

    connection = unittest.mock.Mock()
    connection._RDPConnection__connection = None

    enabled = rdp_pipe.connection_heartbeat.enable_tcp_keepalive_on_connection(connection)

    assert enabled is False


def test_try_enable_tcp_keepalive_logs_oserror():
    """OSError from setsockopt is swallowed after a warning."""

    socket_object = unittest.mock.Mock()
    socket_object.setsockopt.side_effect = OSError("Operation not supported")
    transport_connection = unittest.mock.Mock()
    transport_connection.get_extra_info = unittest.mock.Mock(return_value=socket_object)
    connection = unittest.mock.Mock()
    connection._RDPConnection__connection = transport_connection

    enabled = rdp_pipe.connection_heartbeat.try_enable_tcp_keepalive_on_connection(connection)

    assert enabled is False
