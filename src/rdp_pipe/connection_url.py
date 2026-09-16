"""Normalize RDP URLs and resolve passwords from URL, environment, or stdin."""

import getpass
import os
import re
import sys
import urllib.parse


GENERIC_RDP_SCHEME = "rdp"
DEFAULT_RDP_SCHEME = "rdp+ntlm-password"
PREFERRED_RDP_AUTH_SCHEME = DEFAULT_RDP_SCHEME
RDP_PASSWORD_ENVIRONMENT_VARIABLE = "RDP_PASSWORD"
_BARE_HOST_PATTERN = re.compile(
    r"^[\w.\-:\\]+$")


class ConnectionUrlError(ValueError):
    """Raised when a connection URL or password cannot be resolved."""


def is_generic_rdp_scheme_url(url_text: str) -> bool:
    """Return True when the URL uses rdp:// without an explicit +auth suffix."""

    parsed_url = urllib.parse.urlparse(url_text.strip())

    if "+" in parsed_url.scheme:
        return False

    return parsed_url.scheme.lower() == GENERIC_RDP_SCHEME


def upgrade_generic_rdp_scheme_url(url_text: str) -> str:
    """Rewrite rdp:// to rdp+ntlm-password:// so aardwolf offers NLA-capable protocols."""

    if is_generic_rdp_scheme_url(url_text) is False:
        return url_text

    parsed_url = urllib.parse.urlparse(url_text.strip())

    return urllib.parse.urlunparse((
        PREFERRED_RDP_AUTH_SCHEME,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        parsed_url.query,
        parsed_url.fragment))


def normalize_connection_url(url_text: str) -> str:
    """Return an aardwolf-style URL, expanding bare host shorthand."""

    stripped_url = url_text.strip()
    if stripped_url == "":
        raise ConnectionUrlError("connection URL must not be empty")

    if "://" in stripped_url:
        return upgrade_generic_rdp_scheme_url(stripped_url)

    if _BARE_HOST_PATTERN.match(stripped_url) is None:
        raise ConnectionUrlError(
            "connection URL must include a scheme or be a bare host address")

    return "{scheme}://{host}".format(
        scheme=DEFAULT_RDP_SCHEME,
        host=stripped_url)


def _password_from_url_userinfo(parsed_url: urllib.parse.ParseResult) -> str | None:
    """Return the password embedded in URL userinfo when present."""

    if parsed_url.password is not None and parsed_url.password != "":
        return parsed_url.password

    return None


def _password_from_environment() -> str | None:
    """Return RDP_PASSWORD when set and non-empty."""

    environment_password = os.environ.get(RDP_PASSWORD_ENVIRONMENT_VARIABLE)
    if environment_password is None:
        return None
    if environment_password == "":
        return None

    return environment_password


def _password_from_stdin() -> str:
    """Read password from stdin (getpass on a TTY, otherwise one line)."""

    if sys.stdin.isatty():
        return getpass.getpass("RDP password: ")

    line = sys.stdin.readline()
    if line == "":
        raise ConnectionUrlError(
            "password required but stdin closed before a line was read")

    return line.rstrip("\n")


def resolve_password(url_text: str) -> str:
    """Resolve password using URL userinfo, RDP_PASSWORD, then stdin."""

    normalized_url = normalize_connection_url(url_text)
    parsed_url = urllib.parse.urlparse(normalized_url)

    url_password = _password_from_url_userinfo(parsed_url)
    if url_password is not None:
        return url_password

    environment_password = _password_from_environment()
    if environment_password is not None:
        return environment_password

    return _password_from_stdin()


def _quote_userinfo_component(component_text: str) -> str:
    """Percent-encode a username or password for URL userinfo."""

    return urllib.parse.quote(component_text, safe="")


def inject_password_into_url(url_text: str, password: str) -> str:
    """Return a URL with password embedded in userinfo for aardwolf."""

    normalized_url = normalize_connection_url(url_text)
    parsed_url = urllib.parse.urlparse(normalized_url)

    username = parsed_url.username
    if username is None:
        username = ""

    encoded_username = _quote_userinfo_component(username)
    encoded_password = _quote_userinfo_component(password)
    userinfo = "{username}:{password}".format(
        username=encoded_username,
        password=encoded_password)

    netloc_without_userinfo = parsed_url.hostname
    if parsed_url.port is not None:
        netloc_without_userinfo = "{host}:{port}".format(
            host=netloc_without_userinfo,
            port=parsed_url.port)

    netloc = "{userinfo}@{hostport}".format(
        userinfo=userinfo,
        hostport=netloc_without_userinfo)

    rebuilt = urllib.parse.urlunparse((
        parsed_url.scheme,
        netloc,
        parsed_url.path,
        parsed_url.params,
        parsed_url.query,
        parsed_url.fragment))

    return rebuilt


def prepare_connection_url(url_text: str) -> str:
    """Normalize URL and inject a resolved password when missing from userinfo."""

    normalized_url = normalize_connection_url(url_text)
    parsed_url = urllib.parse.urlparse(normalized_url)

    existing_password = _password_from_url_userinfo(parsed_url)
    if existing_password is not None:
        return normalized_url

    resolved_password = resolve_password(url_text)

    return inject_password_into_url(normalized_url, resolved_password)


def build_session_window_title(connection_url: str) -> str:
    """Return the PyQt6 session window title for a connection URL."""

    parsed_url = urllib.parse.urlparse(connection_url)
    hostname = parsed_url.hostname
    if hostname is None:
        raise ConnectionUrlError("connection URL has no hostname")

    return "RDP - {hostname}".format(hostname=hostname)
