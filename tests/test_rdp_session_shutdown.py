"""Unit tests for graceful GUI session shutdown."""

import queue
import threading
import time
import unittest.mock

import pytest

import rdp_client.rdp_session_thread
import rdp_client.qt_session_window


@pytest.fixture(scope="module")
def qt_application():
    """Provide a single offscreen QApplication for Qt widget tests."""

    import PyQt6.QtWidgets

    qt_application_instance = PyQt6.QtWidgets.QApplication.instance()

    if qt_application_instance is None:
        qt_application_instance = PyQt6.QtWidgets.QApplication([])

    return qt_application_instance


def test_input_forwarder_does_not_forward_none_sentinel():
    """Shutdown sentinel stops the forwarder without enqueueing RDP input."""

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()
    input_queue = queue.Queue()
    input_queue.put("mouse-event")
    input_queue.put(None)

    disconnected_event = threading.Event()
    ext_in_queue = unittest.mock.Mock()
    ext_in_queue.put_nowait = unittest.mock.Mock()

    connection = unittest.mock.Mock()
    connection.disconnected_evt = disconnected_event
    connection.ext_in_queue = ext_in_queue

    session = unittest.mock.Mock()
    session.connection = connection
    worker._session = session
    worker._input_queue = input_queue

    event_loop = unittest.mock.Mock()

    def run_callback_immediately(callback, *callback_arguments):
        callback(*callback_arguments)

    event_loop.call_soon_threadsafe = run_callback_immediately

    worker._input_forwarder(event_loop)

    ext_in_queue.put_nowait.assert_called_once_with("mouse-event")


def test_wait_for_shutdown_joins_async_thread():
    """wait_for_shutdown blocks until the asyncio worker thread exits."""

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()

    def fake_async_thread_main():
        time.sleep(0.05)
        worker._async_thread_finished_event.set()

    with unittest.mock.patch.object(
            worker,
            "_async_thread_main",
            fake_async_thread_main):

        worker.start()
        worker.stop()
        shutdown_finished = worker.wait_for_shutdown(2.0)

    assert shutdown_finished is True
    assert worker._async_thread.is_alive() is False


def test_close_event_calls_wait_for_shutdown(qt_application):
    """Closing the window waits for the RDP session to disconnect."""

    session_window = rdp_client.qt_session_window.RdpSessionWindow.__new__(
        rdp_client.qt_session_window.RdpSessionWindow)
    session_window._shutdown_started = False
    session_window._command_server = None
    session_window._input_queue = queue.Queue()
    session_window._worker = unittest.mock.Mock()
    session_window._worker_thread = unittest.mock.Mock()

    close_event = unittest.mock.Mock()

    with unittest.mock.patch.object(
            rdp_client.qt_session_window.PyQt6.QtWidgets.QMainWindow,
            "closeEvent",
            unittest.mock.Mock()) as main_window_close_event:

        session_window.closeEvent(close_event)

    session_window._worker.stop.assert_called_once()
    session_window._worker.wait_for_shutdown.assert_called_once_with(
        rdp_client.qt_session_window.SESSION_SHUTDOWN_TIMEOUT_SECONDS)
    main_window_close_event.assert_called_once_with(close_event)
