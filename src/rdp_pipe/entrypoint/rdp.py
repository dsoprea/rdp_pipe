"""Connect to an RDP server with a GUI window or headless command socket."""

import argparse
import asyncio
import signal
import sys

import rdp_pipe.command_socket
import rdp_pipe.runtime_paths


DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 800
DEFAULT_COLOR_DEPTH = 32


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
        help="enable JSON-line automation on {0}".format(
            rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH))

    parser.add_argument(
        "--color-depth",
        dest="color_depth",
        type=int,
        choices=(15, 16, 24, 32),
        default=DEFAULT_COLOR_DEPTH,
        help="session bits per pixel (default {0}); affects receive_screenshot and receive_geometry".format(
            DEFAULT_COLOR_DEPTH))

    parser.add_argument(
        "--no-autoresize",
        action="store_true",
        help="do not resize the remote desktop when the local window changes size")

    parser.add_argument(
        "--viewer",
        action="store_true",
        help="ignore local mouse and keyboard input; screen updates only (command pipe unchanged)")

    return parser


def validate_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace):
    """Enforce headless and pipe requirements."""

    if arguments.headless and not arguments.pipe:
        parser.error("--pipe is required when --headless is set")


def write_connection_progress_to_stderr(step_identifier: str):
    """Write one labeled connection step to stderr for headless operators."""

    import rdp_pipe.connection_progress

    step_label = rdp_pipe.connection_progress.get_connection_step_label(
        step_identifier)

    sys.stderr.write("{step_label}\n".format(step_label=step_label))


def run_gui_session(
        connection_url: str,
        command_socket_path: str | None,
        activity_stamp_filepath: str | None,
        color_depth: int,
        autoresize_enabled: bool,
        viewer_mode: bool) -> int:
    """Launch the PyQt6 desktop client."""

    import PyQt6.QtCore
    import PyQt6.QtWidgets

    import rdp_pipe.qt_session_window

    qt_application = PyQt6.QtWidgets.QApplication(sys.argv)
    session_window = rdp_pipe.qt_session_window.RdpSessionWindow(
        connection_url,
        DEFAULT_VIDEO_WIDTH,
        DEFAULT_VIDEO_HEIGHT,
        color_depth=color_depth,
        command_socket_path=command_socket_path,
        activity_stamp_filepath=activity_stamp_filepath,
        autoresize_enabled=autoresize_enabled,
        viewer_mode=viewer_mode)

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

    """Connect headlessly, serve automation commands, and reconnect after drops."""

    import rdp_pipe.command_socket
    import rdp_pipe.connection_error
    import rdp_pipe.connection_progress
    import rdp_pipe.rdp_session_core
    import rdp_pipe.rdp_session_thread

    command_server = None
    current_session = None
    had_successful_session = False
    shutdown_requested = False
    event_loop = asyncio.get_running_loop()
    lifecycle_task = asyncio.current_task()

    def handle_shutdown_signal():
        """Stop the session and cancel connect or output-loop waits on terminal Ctrl+C."""

        nonlocal shutdown_requested

        shutdown_requested = True

        if current_session is not None:
            asyncio.create_task(current_session.stop())

        if lifecycle_task is not None:
            lifecycle_task.cancel()

    event_loop.add_signal_handler(signal.SIGINT, handle_shutdown_signal)
    event_loop.add_signal_handler(signal.SIGTERM, handle_shutdown_signal)

    try:
        while shutdown_requested is False:

            if had_successful_session:
                write_connection_progress_to_stderr(
                    rdp_pipe.connection_progress.CONNECTION_STEP_RECONNECTING)

            session = rdp_pipe.rdp_session_core.RdpAsyncSession(
                connection_url,
                DEFAULT_VIDEO_WIDTH,
                DEFAULT_VIDEO_HEIGHT,
                color_depth=color_depth,
                activity_stamp_filepath=activity_stamp_filepath)

            current_session = session
            session.set_progress_callback(write_connection_progress_to_stderr)

            connect_succeeded = False

            try:
                await session.connect()
                connect_succeeded = True

                if command_server is None:
                    command_server = rdp_pipe.command_socket.CommandSocketServer(
                        command_socket_path,
                        session,
                        log_command_transactions=True)

                    command_server.start()

                    sys.stderr.write(
                        "listening on {socket_path}\n".format(
                            socket_path=command_socket_path))

                else:
                    command_server.set_session(session)

                await session.run_until_stopped()

                if connect_succeeded and shutdown_requested is False:
                    disconnected_stderr = \
                        rdp_pipe.connection_error.format_session_disconnected_reconnecting_stderr(
                            connection_url)
                    sys.stderr.write(disconnected_stderr)

            except asyncio.CancelledError:
                break

            except Exception as error:

                if connect_succeeded:
                    session_ended_stderr = \
                        rdp_pipe.connection_error.format_session_ended_stderr(error)
                    sys.stderr.write(session_ended_stderr)

                else:
                    connection_failure_stderr = \
                        rdp_pipe.connection_error.format_connection_failure_stderr(
                            connection_url,
                            error)
                    sys.stderr.write(connection_failure_stderr)

            finally:
                await session.stop()
                current_session = None

                if connect_succeeded:
                    had_successful_session = True

            if shutdown_requested:
                break

            reconnect_deadline = \
                event_loop.time() + rdp_pipe.rdp_session_thread.SESSION_RECONNECT_DELAY_SECONDS

            while shutdown_requested is False:

                remaining_seconds = reconnect_deadline - event_loop.time()

                if remaining_seconds <= 0:
                    break

                sleep_seconds = \
                    rdp_pipe.rdp_session_thread.SESSION_RECONNECT_POLL_SECONDS

                if remaining_seconds < sleep_seconds:
                    sleep_seconds = remaining_seconds

                await asyncio.sleep(sleep_seconds)

    except asyncio.CancelledError:
        pass

    finally:
        if command_server is not None:
            command_server.stop()

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

    import rdp_pipe.connection_url

    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    validate_arguments(parser, arguments)

    try:
        connection_url = rdp_pipe.connection_url.prepare_connection_url(arguments.url)

    except rdp_pipe.connection_url.ConnectionUrlError as error:
        sys.stderr.write(
            "error: {message}\n".format(message=str(error)))

        return 1

    if arguments.pipe:
        pipe_filepath = rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH
    else:
        pipe_filepath = None

    activity_stamp_filepath = \
        rdp_pipe.runtime_paths.build_default_activity_stamp_filepath()

    if arguments.headless:
        return run_headless_session(
            connection_url,
            pipe_filepath,
            activity_stamp_filepath,
            arguments.color_depth)

    sys.stderr.write("connecting...\n")

    return run_gui_session(
        connection_url,
        pipe_filepath,
        activity_stamp_filepath,
        arguments.color_depth,
        autoresize_enabled=not arguments.no_autoresize,
        viewer_mode=arguments.viewer)


if __name__ == "__main__":
    raise SystemExit(main())
