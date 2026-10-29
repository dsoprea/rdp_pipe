"""RDP Heartbeat PDU on the MCS message channel for connection health probes."""

import aardwolf.protocol.T128.security

CONNECTION_HEARTBEAT_INTERVAL_SECONDS = 15
CONNECTION_HEARTBEAT_MISSED_BEFORE_WARNING = 1
CONNECTION_HEARTBEAT_MISSED_BEFORE_RECONNECT = 2


class TsHeartbeatPdu:
    """MS-RDPBCGR TS_HEARTBEAT_PDU body (reserved, period, count1, count2)."""

    def __init__(
            self,
            period_seconds: int,
            missed_heartbeats_before_warning: int,
            missed_heartbeats_before_reconnect: int):

        """Store heartbeat timing fields for the wire payload."""

        self.period_seconds = period_seconds
        self.missed_heartbeats_before_warning = missed_heartbeats_before_warning
        self.missed_heartbeats_before_reconnect = missed_heartbeats_before_reconnect

    def to_bytes(self) -> bytes:
        """Return the four-byte Heartbeat PDU payload."""

        return bytes([
            0,
            self.period_seconds & 0xFF,
            self.missed_heartbeats_before_warning & 0xFF,
            self.missed_heartbeats_before_reconnect & 0xFF,
        ])


def build_ts_heartbeat_pdu(
        period_seconds: int = CONNECTION_HEARTBEAT_INTERVAL_SECONDS,
        missed_heartbeats_before_warning: int = CONNECTION_HEARTBEAT_MISSED_BEFORE_WARNING,
        missed_heartbeats_before_reconnect: int = CONNECTION_HEARTBEAT_MISSED_BEFORE_RECONNECT) -> TsHeartbeatPdu:
    """Build a Heartbeat PDU with the configured interval and miss thresholds."""

    return TsHeartbeatPdu(
        period_seconds,
        missed_heartbeats_before_warning,
        missed_heartbeats_before_reconnect)


async def send_connection_heartbeat(connection) -> tuple[bool, Exception | None]:
    """Send one Heartbeat PDU on the MCS message channel when the session is up."""

    joined_channels = getattr(connection, "_RDPConnection__joined_channels", None)

    if joined_channels is None:
        return False, None

    try:
        message_channel = joined_channels["MCS"]

    except KeyError:
        return False, None

    heartbeat_pdu = build_ts_heartbeat_pdu()
    security_header = aardwolf.protocol.T128.security.TS_SECURITY_HEADER()
    security_header.flags = \
        aardwolf.protocol.T128.security.SEC_HDR_FLAG.HEARTBEAT

    cryptolayer = getattr(connection, "cryptolayer", None)

    if cryptolayer is not None:
        security_header.flags |= aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT

    send_ok, send_error = await connection.handle_out_data(
        heartbeat_pdu,
        security_header,
        None,
        None,
        message_channel.channel_id,
        False)

    return send_ok, send_error
