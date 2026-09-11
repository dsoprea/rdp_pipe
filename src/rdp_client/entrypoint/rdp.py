"""Connect to an RDP server with a GUI window or headless command socket."""

import argparse
import asyncio
import signal
import sys


DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 800
DEFAULT_COLOR_DEPTH = 32
DEFAULT_PIPE_FILEPATH = "/tmp/rdp.sock"


def build_argument_parser() -> argparse.ArgumentParser:
    """Build argparse parser with -h help."""

    parser = argparse.ArgumentParser(
        description="Connect to an RDP server (NLA / NTLM password).")

    parser.add_argument(
        "url",
        help="rdp://, rdp+ntlm-password://, or bare host (generic rdp:// prefers NTLM; server selects NLA vs TLS vs legacy)")

    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without a GUI; requires --pipe")

    parser.add_argument(
        "--pipe",
        action="store_true",
        help="enable JSON-line automation on {0}".format(DEFAULT_PIPE_FILEPATH))

    parser.add_argument(
        "--activity-stamp-filepath",
        dest="activity_stamp_filepath",
        help="touch this file on each remote framebuffer update")

    parser.add_argument(
        "--color-depth",
        dest="color_depth",
        type=int,
        choices=(15, 16, 24, 32),
        default=DEFAULT_COLOR_DEPTH,
        help="session bits per pixel (default {0}); affects receive_screenshot and receive_geometry".format(
            DEFAULT_COLOR_DEPTH))

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


def run_gui_session(
        connection_url: str,
        command_socket_path: str | None,
        activity_stamp_filepath: str | None,
        color_depth: int) -> int:
    """Launch the PyQt6 desktop client."""

    import PyQt6.QtCore
    import PyQt6.QtWidgets

    import rdp_client.qt_session_window

    qt_application = PyQt6.QtWidgets.QApplication(sys.argv)
    session_window = rdp_client.qt_session_window.RdpSessionWindow(
        connection_url,
        DEFAULT_VIDEO_WIDTH,
        DEFAULT_VIDEO_HEIGHT,
        color_depth=color_depth,
        command_socket_path=command_socket_path,
        activity_stamp_filepath=activity_stamp_filepath)

    session_window.show()

    def handle_terminal_sigint(_signum, _frame):
        """Disconnect the RDP session when the operator presses Ctrl+C in the shell."""

        session_window.close()
        qt_application.quit()

    signal.signal(signal.SIGINT, handle_terminal_sigint)

    # Allow Python to deliver SIGINT while Qt owns the main thread event loop.
    signal_timer = PyQt6.QtCore.QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(200)

    return qt_application.exec()


async def run_headless_session_async(
        connection_url: str,
        command_socket_path: str,
        activity_stamp_filepath: str | None,
        color_depth: int) -> int:

    """Connect headlessly and serve automation commands."""

    import rdp_client.command_socket
    import rdp_client.rdp_session_core

    session = rdp_client.rdp_session_core.RdpAsyncSession(
        connection_url,
        DEFAULT_VIDEO_WIDTH,
        DEFAULT_VIDEO_HEIGHT,
        color_depth=color_depth,
        activity_stamp_filepath=activity_stamp_filepath)

    session.set_progress_callback(write_connection_progress_to_stderr)

    command_server = None
    event_loop = asyncio.get_running_loop()
    lifecycle_task = asyncio.current_task()

    def handle_shutdown_signal():
        """Stop the session and cancel connect or output-loop waits on terminal Ctrl+C."""

        asyncio.create_task(session.stop())

        if lifecycle_task is not None:
            lifecycle_task.cancel()

    event_loop.add_signal_handler(signal.SIGINT, handle_shutdown_signal)
    event_loop.add_signal_handler(signal.SIGTERM, handle_shutdown_signal)

    try:
        await session.connect()

        command_server = rdp_client.command_socket.CommandSocketServer(
            command_socket_path,
            session)

        command_server.start()

        sys.stderr.write(
            "listening on {socket_path}\n".format(socket_path=command_socket_path))

        await session.run_until_stopped()

    except asyncio.CancelledError:
        pass

    finally:
        if command_server is not None:
            command_server.stop()

        await session.stop()

    return 0


def run_headless_session(
        connection_url: str,
        command_socket_path: str,
        activity_stamp_filepath: str | None,
        color_depth: int) -> int:
    """Run the headless asyncio session loop."""

    return asyncio.run(
        run_headless_session_async(
            connection_url,
            command_socket_path,
            activity_stamp_filepath,
            color_depth))


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
            pipe_filepath,
            arguments.activity_stamp_filepath,
            arguments.color_depth)

    sys.stderr.write("connecting...\n")

    return run_gui_session(
        connection_url,
        pipe_filepath,
        arguments.activity_stamp_filepath,
        arguments.color_depth)


if __name__ == "__main__":
    raise SystemExit(main())
