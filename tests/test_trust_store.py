"""Unit tests for ~/.config/rdpipe certificate trust storage."""

import os
import subprocess
import tempfile

import pytest

import rdp_client.trust_store


def _generate_test_certificate_der() -> bytes:
    """Create a short-lived self-signed certificate and return DER bytes."""

    temporary_directory_path = tempfile.mkdtemp()
    certificate_filepath = os.path.join(
        temporary_directory_path,
        "test.pem")
    private_key_filepath = os.path.join(
        temporary_directory_path,
        "test.key")
    der_filepath = os.path.join(
        temporary_directory_path,
        "test.der")

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=trust-store-test",
            "-out",
            certificate_filepath,
            "-keyout",
            private_key_filepath,
        ],
        check=True,
        capture_output=True)

    subprocess.run(
        [
            "openssl",
            "x509",
            "-in",
            certificate_filepath,
            "-outform",
            "DER",
            "-out",
            der_filepath,
        ],
        check=True,
        capture_output=True)

    with open(der_filepath, "rb") as handle:
        der_bytes = handle.read()

    return der_bytes


@pytest.fixture
def config_directory_path(tmp_path):
    """Isolate trust-store files under a temporary config directory."""

    config_root = os.path.join(str(tmp_path), "rdpipe")
    rdp_client.trust_store.set_config_directory_path_for_tests(config_root)

    yield config_root

    rdp_client.trust_store.set_config_directory_path_for_tests(None)


def test_encode_ipv6_client_filename():
    """IPv6 addresses use underscores instead of colons in client filenames."""

    encoded = rdp_client.trust_store.encode_ip_for_client_filename("2001:db8::1")

    assert encoded == "2001_db8__1"


def test_first_connect_creates_client_and_certificate_files(config_directory_path):
    """Unknown IP auto-accepts and writes clients/ and certificates/ entries."""

    der_bytes = _generate_test_certificate_der()
    remote_ip = "10.0.0.5"
    metadata = {
        "hostname": "win10.example",
        "first_seen": "2026-01-01T00:00:00+00:00",
    }

    fingerprint = rdp_client.trust_store.verify_or_accept_server_certificate(
        remote_ip,
        der_bytes,
        metadata,
        config_directory_path)

    client_mapping_filepath = os.path.join(
        config_directory_path,
        "clients",
        "10.0.0.5")
    certificate_directory_path = os.path.join(
        config_directory_path,
        "certificates",
        fingerprint)

    assert os.path.isfile(client_mapping_filepath)
    with open(client_mapping_filepath, encoding="utf-8") as handle:
        assert handle.read().strip() == fingerprint

    assert os.path.isfile(os.path.join(certificate_directory_path, "ip"))
    assert os.path.isfile(os.path.join(certificate_directory_path, "metadata"))
    assert os.path.isfile(os.path.join(certificate_directory_path, "certificate"))


def test_repeat_connect_same_certificate_succeeds(config_directory_path):
    """Known IP with matching fingerprint proceeds without error."""

    der_bytes = _generate_test_certificate_der()
    remote_ip = "10.0.0.6"
    metadata = {"first_seen": "2026-01-01T00:00:00+00:00"}

    first_fingerprint = rdp_client.trust_store.verify_or_accept_server_certificate(
        remote_ip,
        der_bytes,
        metadata,
        config_directory_path)

    second_fingerprint = rdp_client.trust_store.verify_or_accept_server_certificate(
        remote_ip,
        der_bytes,
        metadata,
        config_directory_path)

    assert first_fingerprint == second_fingerprint


def test_fingerprint_mismatch_raises_with_remediation_paths(config_directory_path):
    """Known IP with a different certificate fingerprint is refused."""

    first_der = _generate_test_certificate_der()
    second_der = _generate_test_certificate_der()
    remote_ip = "10.0.0.7"
    metadata = {"first_seen": "2026-01-01T00:00:00+00:00"}

    rdp_client.trust_store.verify_or_accept_server_certificate(
        remote_ip,
        first_der,
        metadata,
        config_directory_path)

    stored_fingerprint = rdp_client.trust_store.load_client_fingerprint(
        remote_ip,
        config_directory_path)

    with pytest.raises(rdp_client.trust_store.CertificateTrustMismatchError) as error_info:
        rdp_client.trust_store.verify_or_accept_server_certificate(
            remote_ip,
            second_der,
            metadata,
            config_directory_path)

    error = error_info.value
    assert error.expected_fingerprint == stored_fingerprint
    assert error.actual_fingerprint != stored_fingerprint
    assert len(error.remediation_paths) == 2
    assert error.remediation_paths[0].endswith(os.path.join("clients", "10.0.0.7"))
    assert error.remediation_paths[1].endswith(stored_fingerprint)


def test_same_certificate_new_ip_reuses_certificate_directory(config_directory_path):
    """A known fingerprint on a new IP writes a second client mapping only."""

    der_bytes = _generate_test_certificate_der()
    first_ip = "10.0.0.8"
    second_ip = "10.0.0.9"
    metadata = {"first_seen": "2026-01-01T00:00:00+00:00"}

    fingerprint = rdp_client.trust_store.verify_or_accept_server_certificate(
        first_ip,
        der_bytes,
        metadata,
        config_directory_path)

    second_fingerprint = rdp_client.trust_store.verify_or_accept_server_certificate(
        second_ip,
        der_bytes,
        metadata,
        config_directory_path)

    assert fingerprint == second_fingerprint

    first_mapping_filepath = os.path.join(
        config_directory_path,
        "clients",
        "10.0.0.8")
    second_mapping_filepath = os.path.join(
        config_directory_path,
        "clients",
        "10.0.0.9")

    assert os.path.isfile(first_mapping_filepath)
    assert os.path.isfile(second_mapping_filepath)


def test_desktop_factory_from_url_returns_desktop_connection():
    """RdpDesktopConnectionFactory.from_url must not return the stock factory type."""

    import aardwolf.commons.iosettings

    import rdp_client.rdp_connection

    iosettings = aardwolf.commons.iosettings.RDPIOSettings()
    connection_factory =         rdp_client.rdp_connection.RdpDesktopConnectionFactory.from_url(
            "rdp+ntlm-password://user:pass@10.0.0.5",
            iosettings)

    assert isinstance(
        connection_factory,
        rdp_client.rdp_connection.RdpDesktopConnectionFactory)

    connection = connection_factory.get_connection(iosettings)

    assert isinstance(
        connection,
        rdp_client.rdp_connection.RdpDesktopConnection)
