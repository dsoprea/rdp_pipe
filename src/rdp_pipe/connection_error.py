"""Classify RDP connect failures and format operator-facing stderr messages."""

import asyncio
import errno
import ssl
import urllib.parse

import rdp_pipe.rdp_session_core
import rdp_pipe.trust_store

DEFAULT_RDP_PORT = 3389
_SERVER_ERROR_PREFIX = "Server replied with error"


def parse_connection_endpoint(connection_url: str) -> str:
    """Return host:port for operator messages parsed from a connection URL."""

    parsed_url = urllib.parse.urlparse(connection_url)
    hostname = parsed_url.hostname

    if parsed_url.port is not None:
        port = parsed_url.port
    else:
        port = DEFAULT_RDP_PORT

    return "{hostname}:{port}".format(hostname=hostname, port=port)


def describe_connection_failure(error: BaseException) -> str:
    """Map a connect exception to a short English reason without a traceback."""

    if isinstance(error, rdp_pipe.trust_store.CertificateTrustMismatchError):
        return str(error)

    if isinstance(error, asyncio.TimeoutError):
        return "connection timed out"

    if isinstance(error, ConnectionResetError):
        return "connection lost"

    if isinstance(error, BrokenPipeError):
        return "connection lost"

    if isinstance(error, OSError):
        if error.errno == errno.ECONNREFUSED:
            return "connection refused"

        if error.errno == errno.EHOSTUNREACH:
            return "no route to host"

        if error.errno == errno.ENETUNREACH:
            return "network unreachable"

        if error.errno == errno.ETIMEDOUT:
            return "connection timed out"

        if error.strerror is not None and error.strerror != "":
            return error.strerror

        return str(error)

    if isinstance(error, ssl.SSLError):
        ssl_detail = str(error)

        if ssl_detail != "":
            return "TLS handshake failed: {detail}".format(detail=ssl_detail)

        return "TLS handshake failed"

    if isinstance(error, rdp_pipe.rdp_session_core.RdpSessionError):
        return str(error)

    error_message = str(error)

    if _SERVER_ERROR_PREFIX in error_message:
        return error_message

    return "connection failed"


def format_connection_failure_stderr(
        connection_url: str,
        error: BaseException) -> str:
    """Return a managed stderr block for a failed connect attempt."""

    if isinstance(error, rdp_pipe.trust_store.CertificateTrustMismatchError):
        return rdp_pipe.trust_store.format_certificate_trust_mismatch_stderr(error)

    endpoint = parse_connection_endpoint(connection_url)
    failure_reason = describe_connection_failure(error)

    return "error: could not connect to {endpoint} ({failure_reason})\n".format(
        endpoint=endpoint,
        failure_reason=failure_reason)


def format_session_ended_stderr(error: BaseException) -> str:
    """Return a managed stderr line when the session ends after connect."""

    failure_reason = describe_connection_failure(error)

    return "error: RDP session ended unexpectedly ({failure_reason})\n".format(
        failure_reason=failure_reason)


def format_session_disconnected_reconnecting_stderr(connection_url: str) -> str:
    """Return a managed stderr line when a live session drops and reconnect begins."""

    endpoint = parse_connection_endpoint(connection_url)

    return "error: RDP session to {endpoint} disconnected; reconnecting...\n".format(
        endpoint=endpoint)
