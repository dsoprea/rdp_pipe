"""Unit tests for connection URL normalization and password resolution."""

import pytest

import rdp_client.connection_url


def test_normalize_bare_host():
    """Bare host shorthand gains the default rdp+ntlm-password scheme."""

    normalized = rdp_client.connection_url.normalize_connection_url("10.0.0.5")

    assert normalized == "rdp+ntlm-password://10.0.0.5"


def test_password_from_url_userinfo():
    """Embedded URL password is returned without environment or stdin."""

    password = rdp_client.connection_url.resolve_password(
        "rdp+ntlm-password://user:secret@10.0.0.5")

    assert password == "secret"


def test_password_from_environment(monkeypatch):
    """RDP_PASSWORD is used when the URL has no password."""

    monkeypatch.setenv(
        rdp_client.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "from-env")

    password = rdp_client.connection_url.resolve_password(
        "rdp+ntlm-password://admin@10.0.0.5")

    assert password == "from-env"


def test_prepare_injects_environment_password(monkeypatch):
    """prepare_connection_url embeds an environment password into userinfo."""

    monkeypatch.setenv(
        rdp_client.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "s3cret")

    prepared_url = rdp_client.connection_url.prepare_connection_url(
        "rdp+ntlm-password://DOMAIN\\Administrator@10.0.0.5")

    assert "s3cret" in prepared_url
    assert "Administrator" in prepared_url


def test_prepare_keeps_existing_url_password(monkeypatch):
    """URL userinfo password wins over RDP_PASSWORD."""

    monkeypatch.setenv(
        rdp_client.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "ignored")

    prepared_url = rdp_client.connection_url.prepare_connection_url(
        "rdp+ntlm-password://user:embedded@10.0.0.5")

    assert "embedded" in prepared_url
    assert "ignored" not in prepared_url


def test_resolve_password_missing_raises(monkeypatch):
    """Missing password with empty env and no stdin raises ConnectionUrlError."""

    monkeypatch.delenv(
        rdp_client.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        raising=False)

    def raise_on_stdin():
        raise rdp_client.connection_url.ConnectionUrlError(
            "password required but stdin closed before a line was read")

    monkeypatch.setattr(
        rdp_client.connection_url,
        "_password_from_stdin",
        raise_on_stdin)

    with pytest.raises(rdp_client.connection_url.ConnectionUrlError):
        rdp_client.connection_url.resolve_password(
            "rdp+ntlm-password://user@10.0.0.5")
