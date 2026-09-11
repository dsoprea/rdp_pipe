"""Connect to a Windows RDP server and open a resizable PyQt6 session window."""

import argparse
import sys

import PyQt6.QtWidgets

import rdp_client.connection_url
import rdp_client.qt_session_window


DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 800


def build_argument_parser() -> argparse.ArgumentParser:
    """Build argparse parser with -h help."""

    parser = argparse.ArgumentParser(
        description="Connect to an RDP server (NLA / NTLM password) and open a desktop window.")

    parser.add_argument(
        "url",
        help="aardwolf-style RDP URL or bare host (normalized to rdp+ntlm-password://)")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Resolve credentials, then run the Qt event loop for the session."""

    parser = build_argument_parser()
    arguments = parser.parse_args(argv)

    try:
        connection_url = rdp_client.connection_url.prepare_connection_url(arguments.url)

    except rdp_client.connection_url.ConnectionUrlError as error:
        sys.stderr.write(
            "error: {message}\n".format(message=str(error)))

        return 1

    sys.stderr.write("connecting...\n")

    qt_application = PyQt6.QtWidgets.QApplication(sys.argv)
    session_window = rdp_client.qt_session_window.RdpSessionWindow(
        connection_url,
        DEFAULT_VIDEO_WIDTH,
        DEFAULT_VIDEO_HEIGHT)

    session_window.show()

    return qt_application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
