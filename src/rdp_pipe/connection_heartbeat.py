"""TCP keepalive on the RDP transport for dead-link detection without RDP Heartbeat PDUs."""

import logging
import socket

_LOGGER = logging.getLogger(__name__)

CONNECTION_KEEPALIVE_IDLE_SECONDS = 15
CONNECTION_KEEPALIVE_INTERVAL_SECONDS = 15
CONNECTION_KEEPALIVE_PROBE_COUNT = 3


def enable_tcp_keepalive_on_connection(connection) -> bool:
    """Turn on SO_KEEPALIVE with a 15-second idle probe interval when supported."""

    transport_connection = getattr(connection, "_RDPConnection__connection", None)

    if transport_connection is None:
        return False

    socket_object = transport_connection.get_extra_info("socket")

    if socket_object is None:
        return False

    socket_object.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    if hasattr(socket, "TCP_KEEPIDLE"):
        socket_object.setsockopt(
            socket.IPPROTO_TCP,
            socket.TCP_KEEPIDLE,
            CONNECTION_KEEPALIVE_IDLE_SECONDS)

    if hasattr(socket, "TCP_KEEPINTVL"):
        socket_object.setsockopt(
            socket.IPPROTO_TCP,
            socket.TCP_KEEPINTVL,
            CONNECTION_KEEPALIVE_INTERVAL_SECONDS)

    if hasattr(socket, "TCP_KEEPCNT"):
        socket_object.setsockopt(
            socket.IPPROTO_TCP,
            socket.TCP_KEEPCNT,
            CONNECTION_KEEPALIVE_PROBE_COUNT)

    return True


def try_enable_tcp_keepalive_on_connection(connection) -> bool:
    """Enable TCP keepalive and log a warning when the socket cannot be configured."""

    try:
        return enable_tcp_keepalive_on_connection(connection)

    except OSError as error:
        _LOGGER.warning(
            "TCP keepalive not enabled on RDP socket: {error}".format(
                error=error))

        return False
