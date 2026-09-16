"""CLI validation tests for rdp."""

import asyncio
import signal
from unittest import mock

import pytest

import rdp_pipe.command_socket
import rdp_pipe.entrypoint.rdp


def test_headless_requires_pipe():
    """--headless without --pipe is rejected."""

    with pytest.raises(SystemExit):
        rdp_pipe.entrypoint.rdp.main(
            ["--headless", "10.0.0.5"])


def test_pipe_without_headless_parses():
    """GUI mode accepts optional --pipe with the default socket path."""

    parser = rdp_pipe.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--pipe", "10.0.0.5"])

    assert arguments.headless is False
    assert arguments.pipe is True


def test_headless_with_pipe_parses():
    """Headless mode accepts --pipe."""

    parser = rdp_pipe.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--headless", "--pipe", "10.0.0.5"])

    assert arguments.headless is True
    assert arguments.pipe is True


def test_write_connection_progress_to_stderr_writes_step_label(capsys):
    """Headless progress callback prints operator-facing step labels."""

    import rdp_pipe.connection_progress

    rdp_pipe.entrypoint.rdp.write_connection_progress_to_stderr(
        rdp_pipe.connection_progress.CONNECTION_STEP_AUTHENTICATING)

    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "Authenticating\n"


def test_help_flag_exits_successfully():
    """-h prints usage and exits zero."""

    with pytest.raises(SystemExit) as exit_info:
        rdp_pipe.entrypoint.rdp.main(["-h"])

    assert exit_info.value.code == 0


def test_color_depth_default_is_32():
    """--color-depth defaults to 32 bpp."""

    parser = rdp_pipe.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(["10.0.0.5"])

    assert arguments.color_depth == rdp_pipe.entrypoint.rdp.DEFAULT_COLOR_DEPTH


def test_color_depth_parses():
    """--color-depth accepts supported bpp values."""

    parser = rdp_pipe.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--color-depth", "24", "10.0.0.5"])

    assert arguments.color_depth == 24


def test_no_autoresize_parses():
    """--no-autoresize disables seamless RDPDISP resize."""

    parser = rdp_pipe.entrypoint.rdp.build_argument_parser()
    default_arguments = parser.parse_args(["10.0.0.5"])
    no_autoresize_arguments = parser.parse_args(
        ["--no-autoresize", "10.0.0.5"])

    assert default_arguments.no_autoresize is False
    assert no_autoresize_arguments.no_autoresize is True


def test_headless_shutdown_signal_handler_stops_session():
    """Terminal Ctrl+C registers SIGINT/SIGTERM handlers that stop the session."""

    shutdown_signal_handlers = {}
    session_stop_called = asyncio.Event()

    class FakeHeadlessSession:
        """Minimal async session stub for headless shutdown tests."""

        def __init__(self, *_args, **_kwargs):
            pass

        def set_progress_callback(self, _callback):
            pass

        async def connect(self):
            await asyncio.Event().wait()

        async def run_until_stopped(self):
            await asyncio.Event().wait()

        async def stop(self):
            session_stop_called.set()

    class FakeCommandSocketServer:
        """Command socket stub that records start/stop calls."""

        def __init__(self, _socket_path, _session):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    async def run_headless_until_signal_registered():
        event_loop = asyncio.get_running_loop()
        original_add_signal_handler = event_loop.add_signal_handler

        def capture_signal_handler(signum, callback):
            shutdown_signal_handlers[signum] = callback

        event_loop.add_signal_handler = capture_signal_handler

        try:
            with mock.patch(
                    "rdp_pipe.rdp_session_core.RdpAsyncSession",
                    FakeHeadlessSession):
                with mock.patch(
                        "rdp_pipe.command_socket.CommandSocketServer",
                        FakeCommandSocketServer):
                    headless_task = asyncio.create_task(
                        rdp_pipe.entrypoint.rdp.run_headless_session_async(
                            "rdp+ntlm-password://user@10.0.0.5",
                            rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH,
                            None,
                            32))

                    await asyncio.sleep(0)

                    shutdown_signal_handlers[signal.SIGINT]()
                    await asyncio.wait_for(session_stop_called.wait(), timeout=1.0)

                    headless_task.cancel()

                    try:
                        await headless_task

                    except asyncio.CancelledError:
                        pass

        finally:
            event_loop.add_signal_handler = original_add_signal_handler

    asyncio.run(run_headless_until_signal_registered())

    assert signal.SIGINT in shutdown_signal_handlers
    assert signal.SIGTERM in shutdown_signal_handlers


def test_gui_terminal_sigint_closes_window_and_quits_application():
    """Terminal Ctrl+C closes the session window and exits the Qt event loop."""

    captured_signal_handlers = {}
    mock_application = mock.Mock()
    mock_application.exec.return_value = 0
    mock_session_window = mock.Mock()
    mock_timer = mock.Mock()

    def capture_signal_handler(signum, handler):
        captured_signal_handlers[signum] = handler

    with mock.patch("signal.signal", capture_signal_handler):
        with mock.patch("PyQt6.QtWidgets.QApplication", return_value=mock_application):
            with mock.patch(
                    "rdp_pipe.qt_session_window.RdpSessionWindow",
                    return_value=mock_session_window):
                with mock.patch("PyQt6.QtCore.QTimer", return_value=mock_timer):
                    exit_code = rdp_pipe.entrypoint.rdp.run_gui_session(
                        "rdp+ntlm-password://user@10.0.0.5",
                        None,
                        None,
                        32,
                        True)

    assert exit_code == 0
    assert signal.SIGINT in captured_signal_handlers
    mock_session_window.show.assert_called_once()
    mock_timer.start.assert_called_once_with(200)

    captured_signal_handlers[signal.SIGINT](signal.SIGINT, None)

    mock_session_window.close.assert_called_once()
    mock_application.quit.assert_called_once()
