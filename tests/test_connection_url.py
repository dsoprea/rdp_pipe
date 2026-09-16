"""Unit tests for connection URL normalization and password resolution."""

import pytest

import rdp_pipe.connection_url


def test_normalize_bare_host():
    """Bare host shorthand gains the default rdp+ntlm-password scheme."""

    normalized = rdp_pipe.connection_url.normalize_connection_url("10.0.0.5")

    assert normalized == "rdp+ntlm-password://10.0.0.5"


def test_normalize_generic_rdp_scheme():
    """Generic rdp:// URLs upgrade to rdp+ntlm-password://."""

    normalized = rdp_pipe.connection_url.normalize_connection_url(
        "rdp://10.0.0.5")

    assert normalized == "rdp+ntlm-password://10.0.0.5"


def test_normalize_explicit_ntlm_scheme_unchanged():
    """Explicit rdp+ntlm-password:// URLs are not rewritten."""

    connection_url = "rdp+ntlm-password://10.0.0.5"
    normalized = rdp_pipe.connection_url.normalize_connection_url(connection_url)

    assert normalized == connection_url


def test_prepare_generic_rdp_injects_password(monkeypatch):
    """Generic rdp:// URLs gain NTLM scheme and an injected password."""

    monkeypatch.setenv(
        rdp_pipe.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "s3cret")

    prepared_url = rdp_pipe.connection_url.prepare_connection_url(
        "rdp://admin@10.0.0.5")

    assert prepared_url.startswith("rdp+ntlm-password://")
    assert "s3cret" in prepared_url
    assert "admin" in prepared_url


def test_prepare_generic_rdp_preserves_userinfo(monkeypatch):
    """Generic rdp:// URLs keep host, port, and domain-qualified username."""

    monkeypatch.setenv(
        rdp_pipe.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "s3cret")

    prepared_url = rdp_pipe.connection_url.prepare_connection_url(
        "rdp://DOMAIN\\Administrator@10.0.0.5:3390")

    assert prepared_url.startswith("rdp+ntlm-password://")
    assert "Administrator" in prepared_url
    assert ":3390" in prepared_url
    assert "s3cret" in prepared_url


def test_prepare_generic_rdp_yields_ntlm_credential():
    """Prepared generic rdp:// URLs parse as NTLM password credentials."""

    import asyauth.common.credentials

    prepared_url = rdp_pipe.connection_url.prepare_connection_url(
        "rdp://user:pass@10.0.0.5")
    credential = asyauth.common.credentials.UniCredential.from_url(prepared_url)

    assert type(credential).__name__ == "NTLMCredential"


def test_password_from_url_userinfo():
    """Embedded URL password is returned without environment or stdin."""

    password = rdp_pipe.connection_url.resolve_password(
        "rdp+ntlm-password://user:secret@10.0.0.5")

    assert password == "secret"


def test_password_from_environment(monkeypatch):
    """RDP_PASSWORD is used when the URL has no password."""

    monkeypatch.setenv(
        rdp_pipe.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "from-env")

    password = rdp_pipe.connection_url.resolve_password(
        "rdp+ntlm-password://admin@10.0.0.5")

    assert password == "from-env"


def test_prepare_injects_environment_password(monkeypatch):
    """prepare_connection_url embeds an environment password into userinfo."""

    monkeypatch.setenv(
        rdp_pipe.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "s3cret")

    prepared_url = rdp_pipe.connection_url.prepare_connection_url(
        "rdp+ntlm-password://DOMAIN\\Administrator@10.0.0.5")

    assert "s3cret" in prepared_url
    assert "Administrator" in prepared_url


def test_prepare_keeps_existing_url_password(monkeypatch):
    """URL userinfo password wins over RDP_PASSWORD."""

    monkeypatch.setenv(
        rdp_pipe.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        "ignored")

    prepared_url = rdp_pipe.connection_url.prepare_connection_url(
        "rdp+ntlm-password://user:embedded@10.0.0.5")

    assert "embedded" in prepared_url
    assert "ignored" not in prepared_url


def test_resolve_password_missing_raises(monkeypatch):
    """Missing password with empty env and no stdin raises ConnectionUrlError."""

    monkeypatch.delenv(
        rdp_pipe.connection_url.RDP_PASSWORD_ENVIRONMENT_VARIABLE,
        raising=False)

    def raise_on_stdin():
        raise rdp_pipe.connection_url.ConnectionUrlError(
            "password required but stdin closed before a line was read")

    monkeypatch.setattr(
        rdp_pipe.connection_url,
        "_password_from_stdin",
        raise_on_stdin)

    with pytest.raises(rdp_pipe.connection_url.ConnectionUrlError):
        rdp_pipe.connection_url.resolve_password(
            "rdp+ntlm-password://user@10.0.0.5")


def test_build_session_window_title_uses_hostname():
    """Window title includes the connection hostname."""

    bare_host_title = rdp_pipe.connection_url.build_session_window_title(
        "rdp+ntlm-password://10.0.0.5")

    assert bare_host_title == "RDP - 10.0.0.5"

    userinfo_title = rdp_pipe.connection_url.build_session_window_title(
        "rdp+ntlm-password://user:secret@win10.example")

    assert userinfo_title == "RDP - win10.example"
