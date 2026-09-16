"""Unit tests for graceful GUI session shutdown."""

import asyncio
import queue
import threading
import time
import unittest.mock

import aardwolf.connection
import pytest

import rdp_client.qt_session_window
import rdp_client.rdp_connection
import rdp_client.rdp_session_thread


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


def test_shutdown_shows_shutting_down_overlay(qt_application):
    """Shutdown displays the shutting-down modal while tearing down resources."""

    session_container = rdp_client.qt_session_window.RdpSessionContainer()
    session_window = rdp_client.qt_session_window.RdpSessionWindow.__new__(
        rdp_client.qt_session_window.RdpSessionWindow)
    session_window._shutdown_started = False
    session_window._command_server = None
    session_window._input_queue = queue.Queue()
    session_window._shutting_down_overlay = session_container.shutting_down_overlay
    session_window._worker = unittest.mock.Mock()
    session_window._worker._async_thread = None
    session_window._worker_thread = unittest.mock.Mock()
    session_window._worker_thread.isRunning.return_value = False

    session_container.show()
    qt_application.processEvents()

    session_window._shutdown_session_resources()

    assert session_container.shutting_down_overlay.isVisible() is True
    session_window._worker.stop.assert_called_once()


def test_wait_for_shutdown_pumps_qt_events(qt_application):
    """Responsive shutdown wait processes Qt events while the worker thread lives."""

    session_window = rdp_client.qt_session_window.RdpSessionWindow.__new__(
        rdp_client.qt_session_window.RdpSessionWindow)
    session_window._worker = unittest.mock.Mock()

    alive_thread = unittest.mock.Mock()
    alive_thread.is_alive.side_effect = [True, False]
    alive_thread.join = unittest.mock.Mock()
    session_window._worker._async_thread = alive_thread

    application = unittest.mock.Mock()
    application.processEvents = unittest.mock.Mock()

    with unittest.mock.patch.object(
            rdp_client.qt_session_window.PyQt6.QtWidgets.QApplication,
            "instance",
            unittest.mock.Mock(return_value=application)):

        shutdown_finished = session_window._wait_for_worker_shutdown_with_responsive_ui(
            1.0)

    assert shutdown_finished is True
    application.processEvents.assert_called()


def test_close_event_calls_wait_for_shutdown(qt_application):
    """Closing the window waits for the RDP session to disconnect."""

    session_window = rdp_client.qt_session_window.RdpSessionWindow.__new__(
        rdp_client.qt_session_window.RdpSessionWindow)
    session_window._shutdown_started = False
    session_window._command_server = None
    session_window._input_queue = queue.Queue()
    session_window._shutting_down_overlay = unittest.mock.Mock()
    session_window._worker = unittest.mock.Mock()
    session_window._worker_thread = unittest.mock.Mock()
    session_window._worker_thread.isRunning.return_value = False

    close_event = unittest.mock.Mock()

    with unittest.mock.patch.object(
            rdp_client.qt_session_window.RdpSessionWindow,
            "_wait_for_worker_shutdown_with_responsive_ui",
            unittest.mock.Mock()) as wait_for_shutdown_with_ui:

        with unittest.mock.patch.object(
                rdp_client.qt_session_window.PyQt6.QtWidgets.QMainWindow,
                "closeEvent",
                unittest.mock.Mock()) as main_window_close_event:

            session_window.closeEvent(close_event)

    session_window._worker.stop.assert_called_once()
    wait_for_shutdown_with_ui.assert_called_once_with(
        rdp_client.qt_session_window.SESSION_SHUTDOWN_TIMEOUT_SECONDS)
    main_window_close_event.assert_called_once_with(close_event)


async def _wait_forever_on_event():
    """Block until cancelled; models aardwolf reader tasks waiting on I/O."""

    await asyncio.Event().wait()


async def _wait_on_queue(waiter_queue):
    """Block on Queue.get until the loop closer cancels the waiter."""

    await waiter_queue.get()


_SCHEDULED_STOP_COROUTINES = []


def _schedule_coroutine_threadsafe(coroutine, event_loop):
    """Record scheduled coroutines instead of running them on a real loop."""

    _SCHEDULED_STOP_COROUTINES.append(coroutine)

    return unittest.mock.Mock()


async def _cancel_reader_tasks_and_return(_connection):
    """Mimic aardwolf terminate: cancel readers without awaiting them."""

    x224_task = _connection._RDPConnection__x224_reader_task
    external_task = _connection._RDPConnection__external_reader_task
    x224_task.cancel()
    external_task.cancel()

    return True, None


async def _run_terminate_with_pending_reader_tasks():
    """Terminate a connection whose aardwolf readers are still waiting."""

    # Build a connection shell with reader tasks that aardwolf would cancel
    # but not await.

    connection = rdp_client.rdp_connection.RdpDesktopConnection.__new__(
        rdp_client.rdp_connection.RdpDesktopConnection)
    connection._share_channel_task = None

    x224_coroutine = _wait_forever_on_event()
    external_coroutine = _wait_forever_on_event()
    x224_task = asyncio.create_task(x224_coroutine)
    external_task = asyncio.create_task(external_coroutine)
    connection._RDPConnection__x224_reader_task = x224_task
    connection._RDPConnection__external_reader_task = external_task

    with unittest.mock.patch.object(
            aardwolf.connection.RDPConnection,
            "terminate",
            _cancel_reader_tasks_and_return):

        await connection.terminate()

    return x224_task.done(), external_task.done()


def test_close_event_loop_after_cancelling_pending_tasks_finishes_queue_waiters():
    """Closing the worker loop must drain Queue.get waiters before loop.close()."""

    event_loop = asyncio.new_event_loop()
    waiter_queue = asyncio.Queue()
    wait_on_queue_coroutine = _wait_on_queue(waiter_queue)
    waiter_task = event_loop.create_task(wait_on_queue_coroutine)

    rdp_client.rdp_session_thread.close_event_loop_after_cancelling_pending_tasks(
        event_loop)

    assert waiter_task.done() is True
    assert event_loop.is_closed() is True


def test_stop_schedules_session_stop_when_session_exists():
    """Window close must terminate the session instead of cancelling the connect task."""

    # Isolate scheduled stop coroutines from other tests that share the list.

    _SCHEDULED_STOP_COROUTINES.clear()

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()
    session = unittest.mock.Mock()
    session.stop = unittest.mock.Mock(return_value="session-stop")

    connection_task = unittest.mock.Mock()
    connection_task.done.return_value = False
    connection_task.cancel = unittest.mock.Mock()

    event_loop = unittest.mock.Mock()
    event_loop.is_running.return_value = True

    worker._session = session
    worker._event_loop = event_loop
    worker._connection_task = connection_task

    with unittest.mock.patch(
            "asyncio.run_coroutine_threadsafe",
            _schedule_coroutine_threadsafe):

        worker.stop()

    connection_task.cancel.assert_not_called()
    event_loop.call_soon_threadsafe.assert_not_called()
    assert _SCHEDULED_STOP_COROUTINES == ["session-stop"]


def test_wait_for_shutdown_timeout_cancels_connection_task_on_event_loop():
    """A shutdown timeout must cancel the connection task on the worker loop."""

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()
    worker._async_thread = unittest.mock.Mock()
    worker._async_thread.is_alive.return_value = True
    worker._async_thread.join = unittest.mock.Mock()

    event_loop = unittest.mock.Mock()
    connection_task = unittest.mock.Mock()
    connection_task.cancel = unittest.mock.Mock()

    worker._event_loop = event_loop
    worker._connection_task = connection_task

    shutdown_finished = worker.wait_for_shutdown(0.01)

    assert shutdown_finished is False
    event_loop.call_soon_threadsafe.assert_called_once_with(connection_task.cancel)
    connection_task.cancel.assert_not_called()


def test_terminate_awaits_cancelled_aardwolf_reader_tasks():
    """terminate() must await aardwolf reader tasks after cancelling them."""

    terminate_reader_run = _run_terminate_with_pending_reader_tasks()
    x224_done, external_done = asyncio.run(terminate_reader_run)

    assert x224_done is True
    assert external_done is True


async def _simulate_x224_reader_finally_terminate(connection):
    """Call terminate() from inside the x224 reader task like aardwolf does."""

    connection._RDPConnection__x224_reader_task = asyncio.current_task()

    external_coroutine = _wait_forever_on_event()
    external_task = asyncio.create_task(external_coroutine)
    connection._RDPConnection__external_reader_task = external_task

    with unittest.mock.patch.object(
            aardwolf.connection.RDPConnection,
            "terminate",
            _cancel_reader_tasks_and_return):

        await connection.terminate()


async def _run_nested_terminate_from_x224_reader():
    """Exercise nested terminate while the x224 reader task is still current."""

    connection = rdp_client.rdp_connection.RdpDesktopConnection.__new__(
        rdp_client.rdp_connection.RdpDesktopConnection)
    connection._share_channel_task = None
    connection._terminate_in_progress = False

    reader_coroutine = _simulate_x224_reader_finally_terminate(connection)
    reader_task = asyncio.create_task(reader_coroutine)

    await reader_task

    return reader_task.done()


def test_terminate_from_x224_reader_finally_does_not_await_current_task():
    """Nested terminate from __x224_reader finally must not await the current task."""

    reader_done = asyncio.run(_run_nested_terminate_from_x224_reader())

    assert reader_done is True


def test_stop_cancels_connection_task_when_session_is_missing():
    """Cancel the connect task only when the session object does not exist yet."""

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()
    worker._session = None

    event_loop = unittest.mock.Mock()
    event_loop.is_running.return_value = True

    connection_task = unittest.mock.Mock()
    connection_task.done.return_value = False

    worker._event_loop = event_loop
    worker._connection_task = connection_task

    worker.stop()

    event_loop.call_soon_threadsafe.assert_called_once_with(connection_task.cancel)


async def _hang_until_cancelled(_connection):
    """Block aardwolf terminate so the disconnect timeout fires."""

    await asyncio.Event().wait()


async def _run_terminate_with_hanging_parent():
    """Terminate while aardwolf send_disconnect never returns."""

    # Force the disconnect timeout so terminate() must close the transport
    # itself instead of waiting on MCS.out_queue.

    connection = rdp_client.rdp_connection.RdpDesktopConnection.__new__(
        rdp_client.rdp_connection.RdpDesktopConnection)
    connection._share_channel_task = None
    connection._RDPConnection__x224_reader_task = None
    connection._RDPConnection__external_reader_task = None

    transport_connection = unittest.mock.AsyncMock()
    connection._RDPConnection__connection = transport_connection

    with unittest.mock.patch.object(
            rdp_client.rdp_connection,
            "TERMINATE_DISCONNECT_TIMEOUT_SECONDS",
            0.05):

        with unittest.mock.patch.object(
                aardwolf.connection.RDPConnection,
                "terminate",
                _hang_until_cancelled):

            await connection.terminate()

    return transport_connection.close.await_count


def test_terminate_timeout_closes_aardwolf_transport():
    """A wedged send_disconnect must still close the aardwolf transport."""

    hanging_terminate_run = _run_terminate_with_hanging_parent()
    close_await_count = asyncio.run(hanging_terminate_run)

    assert close_await_count == 1


def test_close_event_loop_with_no_pending_tasks_closes_loop():
    """An idle worker loop must still shut down asyncgens and close."""

    event_loop = asyncio.new_event_loop()

    rdp_client.rdp_session_thread.close_event_loop_after_cancelling_pending_tasks(
        event_loop)

    assert event_loop.is_closed() is True
