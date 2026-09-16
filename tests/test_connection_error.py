"""Tests for connection failure classification and stderr formatting."""

import asyncio
import errno
import os

import pytest

import rdp_client.connection_error
import rdp_client.rdp_session_core
import rdp_client.trust_store


def test_describe_connection_failure_host_unreachable():
    """EHOSTUNREACH maps to a no-route-to-host message."""

    connect_error = OSError(errno.EHOSTUNREACH, "No route to host")

    failure_reason = rdp_client.connection_error.describe_connection_failure(
        connect_error)

    assert failure_reason == "no route to host"


def test_describe_connection_failure_connection_refused():
    """ECONNREFUSED maps to connection refused."""

    connect_error = OSError(errno.ECONNREFUSED, "Connection refused")

    failure_reason = rdp_client.connection_error.describe_connection_failure(
        connect_error)

    assert failure_reason == "connection refused"


def test_describe_connection_failure_timeout():
    """asyncio.TimeoutError maps to connection timed out."""

    failure_reason = rdp_client.connection_error.describe_connection_failure(
        asyncio.TimeoutError())

    assert failure_reason == "connection timed out"


def test_describe_connection_failure_connection_reset():
    """ConnectionResetError maps to connection lost."""

    failure_reason = rdp_client.connection_error.describe_connection_failure(
        ConnectionResetError("Connection lost"))

    assert failure_reason == "connection lost"


def test_parse_connection_endpoint_default_port():
    """Bare host URLs use the default RDP port in endpoint messages."""

    endpoint = rdp_client.connection_error.parse_connection_endpoint(
        "rdp+ntlm-password://user:secret@10.0.0.7")

    assert endpoint == "10.0.0.7:3389"


def test_parse_connection_endpoint_explicit_port():
    """Explicit URL ports are preserved in endpoint messages."""

    endpoint = rdp_client.connection_error.parse_connection_endpoint(
        "rdp+ntlm-password://user:secret@10.0.0.7:3390")

    assert endpoint == "10.0.0.7:3390"


def test_format_connection_failure_stderr_includes_error_prefix():
    """Managed connect failures include host:port and an error prefix."""

    connection_url = "rdp+ntlm-password://user:secret@10.0.0.7:3390"
    connect_error = OSError(errno.EHOSTUNREACH, "No route to host")

    stderr_text = rdp_client.connection_error.format_connection_failure_stderr(
        connection_url,
        connect_error)

    assert stderr_text.startswith(
        "error: could not connect to 10.0.0.7:3390 (no route to host)")
    assert stderr_text.endswith("\n")


def test_format_connection_failure_stderr_delegates_trust_mismatch():
    """Certificate trust mismatch uses the trust_store remediation formatter."""

    remediation_paths = [
        os.path.join("/tmp/rdpipe", "clients", "10.0.0.7"),
        os.path.join("/tmp/rdpipe", "certificates", "abc123"),
    ]
    trust_error = rdp_client.trust_store.CertificateTrustMismatchError(
        "10.0.0.7",
        "expected-fingerprint",
        "actual-fingerprint",
        remediation_paths)

    stderr_text = rdp_client.connection_error.format_connection_failure_stderr(
        "rdp+ntlm-password://10.0.0.7",
        trust_error)

    assert "error: certificate fingerprint mismatch for 10.0.0.7" in stderr_text
    assert "stored fingerprint: expected-fingerprint" in stderr_text


def test_format_session_ended_stderr():
    """Post-connect session failures use a distinct managed stderr line."""

    session_error = rdp_client.rdp_session_core.RdpSessionError(
        "desktop buffer has no image data yet")

    stderr_text = rdp_client.connection_error.format_session_ended_stderr(
        session_error)

    assert stderr_text == \
        "error: RDP session ended unexpectedly (desktop buffer has no image data yet)\n"
