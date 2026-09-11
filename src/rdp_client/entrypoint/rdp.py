"""Connect to an RDP server with a GUI window or headless command socket."""

import argparse
import asyncio
import sys


DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 800
DEFAULT_PIPE_FILEPATH = "/tmp/rdp.sock"


def build_argument_parser() -> argparse.ArgumentParser:
    """Build argparse parser with -h help."""

    parser = argparse.ArgumentParser(
        description="Connect to an RDP server (NLA / NTLM password).")

    parser.add_argument(
        "url",
        help="aardwolf-style RDP URL or bare host (normalized to rdp+ntlm-password://)")

    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without a GUI; requires --pipe")

    parser.add_argument(
        "--pipe",
        action="store_true",
        help="enable JSON-line automation on {0}".format(DEFAULT_PIPE_FILEPATH))

    return parser


def validate_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace):
    """Enforce headless and pipe requirements."""

    if arguments.headless and not arguments.pipe:
        parser.error("--pipe is required when --headless is set")


def write_connection_progress_to_stderr(step_identifier: str):
    """Write one labeled connection step to stderr for headless operators."""

    import rdp_client.connection_progress

    step_label = rdp_client.connection_progress.get_connection_step_label(
        step_identifier)

    sys.stderr.write("{step_label}\n".format(step_label=step_label))


def run_gui_session(connection_url: str, command_socket_path: str | None) -> int:
    """Launch the PyQt6 desktop client."""

    import PyQt6.QtWidgets

    import rdp_client.qt_session_window

    qt_application = PyQt6.QtWidgets.QApplication(sys.argv)
    session_window = rdp_client.qt_session_window.RdpSessionWindow(
        connection_url,
        DEFAULT_VIDEO_WIDTH,
        DEFAULT_VIDEO_HEIGHT,
        command_socket_path=command_socket_path)

    session_window.show()

    return qt_application.exec()


async def run_headless_session_async(
        connection_url: str,
        command_socket_path: str) -> int:

    """Connect headlessly and serve automation commands."""

    import rdp_client.rdp_session_core

    session = rdp_client.rdp_session_core.RdpAsyncSession(
        connection_url,
        DEFAULT_VIDEO_WIDTH,
        DEFAULT_VIDEO_HEIGHT)

    session.set_progress_callback(write_connection_progress_to_stderr)

    await session.connect()

    import rdp_client.command_socket

    command_server = rdp_client.command_socket.CommandSocketServer(
        command_socket_path,
        session)

    command_server.start()

    sys.stderr.write(
        "listening on {socket_path}\n".format(socket_path=command_socket_path))

    session_task = asyncio.create_task(session.run_until_stopped())

    try:
        await session_task

    except asyncio.CancelledError:
        pass

    finally:
        command_server.stop()
        await session.stop()

    return 0


def run_headless_session(connection_url: str, command_socket_path: str) -> int:
    """Run the headless asyncio session loop."""

    return asyncio.run(
        run_headless_session_async(connection_url, command_socket_path))


def main(argv: list[str] | None = None) -> int:
    """Resolve credentials, then run GUI or headless mode."""

    import rdp_client.connection_url

    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    validate_arguments(parser, arguments)

    try:
        connection_url = rdp_client.connection_url.prepare_connection_url(arguments.url)

    except rdp_client.connection_url.ConnectionUrlError as error:
        sys.stderr.write(
            "error: {message}\n".format(message=str(error)))

        return 1

    if arguments.pipe:
        pipe_filepath = DEFAULT_PIPE_FILEPATH
    else:
        pipe_filepath = None

    if arguments.headless:
        return run_headless_session(
            connection_url,
            pipe_filepath)

    sys.stderr.write("connecting...\n")

    return run_gui_session(connection_url, pipe_filepath)


if __name__ == "__main__":
    raise SystemExit(main())
