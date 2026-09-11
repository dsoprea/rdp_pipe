"""Persist server certificates and IP-to-fingerprint mappings under ~/.config/rdpipe."""

import datetime
import hashlib
import json
import os
import ssl


_CONFIG_DIRECTORY_PATH_OVERRIDE = None

CERTIFICATES_DIRECTORY_NAME = "certificates"
KEYS_DIRECTORY_NAME = "keys"
CLIENTS_DIRECTORY_NAME = "clients"

IP_FILENAME = "ip"
METADATA_FILENAME = "metadata"
CERTIFICATE_FILENAME = "certificate"
PUBLIC_KEY_FILENAME = "public_key"


class CertificateTrustMismatchError(Exception):
    """Raised when a known IP presents a different certificate fingerprint."""

    def __init__(
            self,
            remote_ip: str,
            expected_fingerprint: str,
            actual_fingerprint: str,
            remediation_paths: list[str]):

        """Store mismatch details and operator remediation paths."""

        self.remote_ip = remote_ip
        self.expected_fingerprint = expected_fingerprint
        self.actual_fingerprint = actual_fingerprint
        self.remediation_paths = remediation_paths

        message = \
            "certificate fingerprint mismatch for {remote_ip}".format(
                remote_ip=remote_ip)

        super().__init__(message)


def get_config_directory_path() -> str:
    """Return the rdpipe config root, honoring a test override when set."""

    if _CONFIG_DIRECTORY_PATH_OVERRIDE is not None:
        return _CONFIG_DIRECTORY_PATH_OVERRIDE

    return os.path.join(
        os.path.expanduser("~"),
        ".config",
        "rdpipe")


def set_config_directory_path_for_tests(config_directory_path: str | None) -> None:
    """Point trust-store paths at a temporary directory during unit tests."""

    global _CONFIG_DIRECTORY_PATH_OVERRIDE

    _CONFIG_DIRECTORY_PATH_OVERRIDE = config_directory_path


def encode_ip_for_client_filename(remote_ip: str) -> str:
    """Encode a remote IP as a safe clients/ filename (IPv6 colons become underscores)."""

    return remote_ip.replace(":", "_")


def compute_certificate_fingerprint(der_bytes: bytes) -> str:
    """Return lowercase SHA-256 hex of the DER-encoded certificate."""

    digest = hashlib.sha256(der_bytes)

    return digest.hexdigest()


def build_certificate_pem(der_bytes: bytes) -> str:
    """Convert DER certificate bytes to PEM text."""

    pem_text = ssl.DER_cert_to_PEM_cert(der_bytes)

    return pem_text


def _get_certificates_directory_path(config_directory_path: str | None = None) -> str:
    """Return the certificates storage directory path."""

    if config_directory_path is None:
        config_directory_path = get_config_directory_path()

    return os.path.join(
        config_directory_path,
        CERTIFICATES_DIRECTORY_NAME)


def _get_keys_directory_path(config_directory_path: str | None = None) -> str:
    """Return the public-key storage directory path."""

    if config_directory_path is None:
        config_directory_path = get_config_directory_path()

    return os.path.join(
        config_directory_path,
        KEYS_DIRECTORY_NAME)


def _get_clients_directory_path(config_directory_path: str | None = None) -> str:
    """Return the IP-to-fingerprint clients mapping directory path."""

    if config_directory_path is None:
        config_directory_path = get_config_directory_path()

    return os.path.join(
        config_directory_path,
        CLIENTS_DIRECTORY_NAME)


def _get_client_mapping_filepath(
        remote_ip: str,
        config_directory_path: str | None = None) -> str:

    """Return the filepath for an IP-based client fingerprint mapping."""

    clients_directory_path = _get_clients_directory_path(config_directory_path)
    ip_filename = encode_ip_for_client_filename(remote_ip)

    return os.path.join(
        clients_directory_path,
        ip_filename)


def _get_certificate_directory_path(
        fingerprint: str,
        config_directory_path: str | None = None) -> str:

    """Return the directory path for a stored certificate fingerprint."""

    certificates_directory_path = _get_certificates_directory_path(config_directory_path)

    return os.path.join(
        certificates_directory_path,
        fingerprint)


def _get_key_directory_path(
        fingerprint: str,
        config_directory_path: str | None = None) -> str:

    """Return the directory path for a stored public-key fingerprint."""

    keys_directory_path = _get_keys_directory_path(config_directory_path)

    return os.path.join(
        keys_directory_path,
        fingerprint)


def _write_text_file(filepath: str, text: str) -> None:
    """Write a text file, creating parent directories as needed."""

    parent_directory_path = os.path.dirname(filepath)
    os.makedirs(parent_directory_path, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read_text_file(filepath: str) -> str:
    """Read a text file and return its contents."""

    with open(filepath, encoding="utf-8") as handle:
        return handle.read()


def load_client_fingerprint(
        remote_ip: str,
        config_directory_path: str | None = None) -> str | None:

    """Return the stored fingerprint for remote_ip, or None when unmapped."""

    client_mapping_filepath = _get_client_mapping_filepath(
        remote_ip,
        config_directory_path)

    if not os.path.isfile(client_mapping_filepath):
        return None

    mapping_text = _read_text_file(client_mapping_filepath)

    return mapping_text.strip()


def write_client_mapping(
        remote_ip: str,
        fingerprint: str,
        config_directory_path: str | None = None) -> None:

    """Write the IP-to-fingerprint mapping file for remote_ip."""

    client_mapping_filepath = _get_client_mapping_filepath(
        remote_ip,
        config_directory_path)

    _write_text_file(
        client_mapping_filepath,
        fingerprint)


def _load_metadata(
        metadata_filepath: str) -> dict:

    """Load JSON metadata from disk, returning an empty dict when missing."""

    if not os.path.isfile(metadata_filepath):
        return {}

    metadata_text = _read_text_file(metadata_filepath)
    metadata = json.loads(metadata_text)

    return metadata


def _write_metadata(
        metadata_filepath: str,
        metadata: dict) -> None:

    """Write JSON metadata to disk."""

    metadata_text = json.dumps(
        metadata,
        indent=2,
        sort_keys=True)

    _write_text_file(
        metadata_filepath,
        metadata_text)


def store_certificate(
        remote_ip: str,
        der_bytes: bytes,
        metadata_dict: dict,
        config_directory_path: str | None = None) -> str:

    """Persist a server certificate and return its fingerprint."""

    fingerprint = compute_certificate_fingerprint(der_bytes)
    certificate_directory_path = _get_certificate_directory_path(
        fingerprint,
        config_directory_path)

    os.makedirs(certificate_directory_path, exist_ok=True)

    ip_filepath = os.path.join(
        certificate_directory_path,
        IP_FILENAME)
    metadata_filepath = os.path.join(
        certificate_directory_path,
        METADATA_FILENAME)
    certificate_filepath = os.path.join(
        certificate_directory_path,
        CERTIFICATE_FILENAME)

    if not os.path.isfile(ip_filepath):
        _write_text_file(
            ip_filepath,
            remote_ip)

    if not os.path.isfile(certificate_filepath):
        pem_text = build_certificate_pem(der_bytes)
        _write_text_file(
            certificate_filepath,
            pem_text)

    existing_metadata = _load_metadata(metadata_filepath)
    merged_metadata = dict(existing_metadata)
    merged_metadata.update(metadata_dict)

    seen_ips = merged_metadata.get("seen_ips")
    if seen_ips is None:
        seen_ips = []

    if remote_ip not in seen_ips:
        seen_ips.append(remote_ip)

    merged_metadata["seen_ips"] = seen_ips
    merged_metadata["last_seen_ip"] = remote_ip

    _write_metadata(
        metadata_filepath,
        merged_metadata)

    return fingerprint


def store_public_key(
        remote_ip: str,
        public_key_text: str,
        fingerprint: str,
        metadata_dict: dict,
        config_directory_path: str | None = None) -> str:

    """Persist a public key under keys/<fingerprint>/ and return the fingerprint."""

    key_directory_path = _get_key_directory_path(
        fingerprint,
        config_directory_path)

    os.makedirs(key_directory_path, exist_ok=True)

    ip_filepath = os.path.join(
        key_directory_path,
        IP_FILENAME)
    metadata_filepath = os.path.join(
        key_directory_path,
        METADATA_FILENAME)
    public_key_filepath = os.path.join(
        key_directory_path,
        PUBLIC_KEY_FILENAME)

    if not os.path.isfile(ip_filepath):
        _write_text_file(
            ip_filepath,
            remote_ip)

    if not os.path.isfile(public_key_filepath):
        _write_text_file(
            public_key_filepath,
            public_key_text)

    existing_metadata = _load_metadata(metadata_filepath)
    merged_metadata = dict(existing_metadata)
    merged_metadata.update(metadata_dict)

    seen_ips = merged_metadata.get("seen_ips")
    if seen_ips is None:
        seen_ips = []

    if remote_ip not in seen_ips:
        seen_ips.append(remote_ip)

    merged_metadata["seen_ips"] = seen_ips
    merged_metadata["last_seen_ip"] = remote_ip

    _write_metadata(
        metadata_filepath,
        merged_metadata)

    return fingerprint


def build_remediation_paths(
        remote_ip: str,
        expected_fingerprint: str,
        config_directory_path: str | None = None) -> list[str]:

    """Return filesystem paths the operator may remove to fix a fingerprint mismatch."""

    client_mapping_filepath = _get_client_mapping_filepath(
        remote_ip,
        config_directory_path)
    certificate_directory_path = _get_certificate_directory_path(
        expected_fingerprint,
        config_directory_path)

    return [
        client_mapping_filepath,
        certificate_directory_path,
    ]


def format_certificate_trust_mismatch_stderr(error: CertificateTrustMismatchError) -> str:
    """Format a human-readable stderr message with remediation paths."""

    lines = [
        "error: certificate fingerprint mismatch for {remote_ip}".format(
            remote_ip=error.remote_ip),
        "  stored fingerprint: {expected}".format(
            expected=error.expected_fingerprint),
        "  presented fingerprint: {actual}".format(
            actual=error.actual_fingerprint),
        "  to trust the new certificate, remove:",
        "    {client_mapping_path}".format(
            client_mapping_path=error.remediation_paths[0]),
        "  optional (drops stored certificate for old fingerprint):",
        "    {certificate_directory_path}".format(
            certificate_directory_path=error.remediation_paths[1]),
        "",
    ]

    return "\n".join(lines)


def verify_or_accept_server_certificate(
        remote_ip: str,
        der_bytes: bytes,
        metadata_dict: dict,
        config_directory_path: str | None = None) -> str:

    """Apply TOFU trust policy and return the certificate fingerprint on success."""

    actual_fingerprint = compute_certificate_fingerprint(der_bytes)
    stored_fingerprint = load_client_fingerprint(
        remote_ip,
        config_directory_path)

    if stored_fingerprint is None:
        write_client_mapping(
            remote_ip,
            actual_fingerprint,
            config_directory_path)

        store_certificate(
            remote_ip,
            der_bytes,
            metadata_dict,
            config_directory_path)

        return actual_fingerprint

    if stored_fingerprint != actual_fingerprint:
        remediation_paths = build_remediation_paths(
            remote_ip,
            stored_fingerprint,
            config_directory_path)

        raise CertificateTrustMismatchError(
            remote_ip,
            stored_fingerprint,
            actual_fingerprint,
            remediation_paths)

    metadata_with_touch = dict(metadata_dict)
    metadata_with_touch["last_seen"] = \
        datetime.datetime.now(datetime.UTC).isoformat()

    store_certificate(
        remote_ip,
        der_bytes,
        metadata_with_touch,
        config_directory_path)

    return actual_fingerprint
