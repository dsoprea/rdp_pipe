"""Qt thread bridge for asyncio RDP sessions."""

import asyncio
import logging
import sys
import queue
import threading
import aardwolf.commons.queuedata
import PyQt6.QtCore

import rdp_pipe.connection_error
import rdp_pipe.keyboard_debug
import rdp_pipe.connection_progress
import rdp_pipe.pointer_update
import rdp_pipe.rdp_session_core


_LOGGER = logging.getLogger(__name__)

SESSION_RECONNECT_DELAY_SECONDS = 1.0
SESSION_RECONNECT_POLL_SECONDS = 0.1
ASYNC_THREAD_FORCE_SHUTDOWN_JOIN_SECONDS = 2.0


def _run_event_loop_shutdown_step(
        event_loop: asyncio.AbstractEventLoop,
        shutdown_step) -> None:
    """Run one asyncio shutdown step; tolerate loop.stop() from forced shutdown."""

    if event_loop.is_closed():
        return

    try:
        event_loop.run_until_complete(shutdown_step)

    except RuntimeError as error:

        # force_async_thread_shutdown() can call loop.stop() while this thread is
        # still draining pending tasks or shutting down the default executor.

        error_message = str(error)

        if "Event loop stopped" not in error_message:
            raise


def close_event_loop_after_cancelling_pending_tasks(
        event_loop: asyncio.AbstractEventLoop) -> None:
    """Cancel leftover tasks, shut down asyncio resources, then close the loop."""

    # aardwolf leaves reader and channel tasks pending after terminate();
    # closing the loop under those waiters raises Event loop is closed.

    pending_tasks = asyncio.all_tasks(event_loop)
    for pending_task in pending_tasks:
        pending_task.cancel()

    if len(pending_tasks) > 0:

        gather_pending = asyncio.gather(
            *pending_tasks,
            return_exceptions=True)
        _run_event_loop_shutdown_step(event_loop, gather_pending)

    # Match asyncio.run() so async generators and the default executor exit
    # before the loop is closed.

    shutdown_asyncgens = event_loop.shutdown_asyncgens()
    _run_event_loop_shutdown_step(event_loop, shutdown_asyncgens)
    shutdown_default_executor = event_loop.shutdown_default_executor()
    _run_event_loop_shutdown_step(event_loop, shutdown_default_executor)

    if event_loop.is_closed() is False:
        event_loop.close()


class RdpVideoFrame(rdp_pipe.rdp_session_core.RdpVideoFrame):
    """Partial framebuffer update emitted to the Qt main thread."""

    pass


class RdpSessionWorker(PyQt6.QtCore.QObject):
    """Runs RdpAsyncSession on a background Qt thread."""

    video_frame_ready = PyQt6.QtCore.pyqtSignal(object)
    pointer_update_ready = PyQt6.QtCore.pyqtSignal(object)
    connection_terminated = PyQt6.QtCore.pyqtSignal()
    resolution_changed = PyQt6.QtCore.pyqtSignal(int, int)
    display_caps_unavailable = PyQt6.QtCore.pyqtSignal()
    session_ready = PyQt6.QtCore.pyqtSignal(object)
    clipboard_text_ready = PyQt6.QtCore.pyqtSignal(str)
    connection_progress = PyQt6.QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        """Initialize worker state; call set_session before start."""

        super().__init__(parent)

        self._connection_url = None
        self._video_width = None
        self._video_height = None
        self._color_depth = None
        self._activity_stamp_filepath = None
        self._input_queue = None
        self._session: rdp_pipe.rdp_session_core.RdpAsyncSession | None = None
        self._event_loop = None
        self._gui_stopped_event = threading.Event()
        self._async_thread_finished_event = threading.Event()
        self._async_thread = None
        self._connection_task = None
        self._input_forwarder_future = None
        self._stop_future = None

    def set_session(
            self,
            connection_url: str,
            video_width: int,
            video_height: int,
            input_queue: queue.Queue,
            color_depth: int = 32,
            activity_stamp_filepath: str | None = None):

        """Bind URL, video geometry, and the GUI input queue."""

        self._connection_url = connection_url
        self._video_width = video_width
        self._video_height = video_height
        self._color_depth = color_depth
        self._activity_stamp_filepath = activity_stamp_filepath
        self._input_queue = input_queue

    def get_session(self) -> rdp_pipe.rdp_session_core.RdpAsyncSession | None:
        """Return the active session after session_ready fires."""

        return self._session

    def _input_forwarder(self, event_loop: asyncio.AbstractEventLoop):
        """Forward GUI input queue items into the connection ext_in_queue."""

        while not self._session.connection.disconnected_evt.is_set():
            input_item = self._input_queue.get()

            if input_item is None:
                break

            if rdp_pipe.keyboard_debug.is_keyboard_debug_enabled():
                input_type = getattr(input_item, "type", None)

                if input_type in (
                        aardwolf.commons.queuedata.RDPDATATYPE.KEYSCAN,
                        aardwolf.commons.queuedata.RDPDATATYPE.KEYUNICODE):

                    rdp_pipe.keyboard_debug.write_keyboard_debug(
                        "keyboard forwarder dequeued type={input_type}".format(
                            input_type=input_type))

            event_loop.call_soon_threadsafe(
                self._session.connection.ext_in_queue.put_nowait,
                input_item)

    def _emit_video_frame(self, video_frame: rdp_pipe.rdp_session_core.RdpVideoFrame):
        """Bridge core video frames to the Qt signal."""

        if self._gui_stopped_event.is_set():
            return

        qt_video_frame = RdpVideoFrame(
            video_frame.x_position,
            video_frame.y_position,
            video_frame.image,
            video_frame.width,
            video_frame.height)

        self.video_frame_ready.emit(qt_video_frame)

    def _emit_pointer_update(self, pointer_update: rdp_pipe.pointer_update.RdpPointerUpdate):
        """Bridge server pointer updates to the Qt signal."""

        if self._gui_stopped_event.is_set():
            return

        self.pointer_update_ready.emit(pointer_update)

    def _emit_resolution_changed(self, width: int, height: int):
        """Bridge resolution changes to the Qt signal."""

        self.resolution_changed.emit(width, height)

    def _emit_clipboard_text(self, clipboard_text: str):
        """Bridge remote clipboard text to the Qt main thread."""

        if self._gui_stopped_event.is_set():
            return

        self.clipboard_text_ready.emit(clipboard_text)

    def _emit_connection_progress(self, step_identifier: str):
        """Bridge connection progress updates to the Qt signal."""

        if self._gui_stopped_event.is_set():
            return

        self.connection_progress.emit(step_identifier)

    async def _wait_before_reconnect(self):
        """Pause between reconnect attempts while honoring cooperative shutdown."""

        deadline = asyncio.get_event_loop().time() + SESSION_RECONNECT_DELAY_SECONDS

        while self._gui_stopped_event.is_set() is False:

            remaining_seconds = deadline - asyncio.get_event_loop().time()

            if remaining_seconds <= 0:
                return

            sleep_seconds = SESSION_RECONNECT_POLL_SECONDS

            if remaining_seconds < sleep_seconds:
                sleep_seconds = remaining_seconds

            await asyncio.sleep(sleep_seconds)

    async def _poll_gui_shutdown_during_connect(self):
        """Wake when the Qt thread requests shutdown during an in-flight connect."""

        while self._gui_stopped_event.is_set() is False:
            await asyncio.sleep(SESSION_RECONNECT_POLL_SECONDS)

    async def _connect_session_unless_gui_stopped(self):
        """Connect unless window close was requested while TCP handshake is pending."""

        connect_task = asyncio.create_task(self._session.connect())
        shutdown_poll_task = asyncio.create_task(self._poll_gui_shutdown_during_connect())

        done_tasks, pending_tasks = await asyncio.wait(
            [connect_task, shutdown_poll_task],
            return_when=asyncio.FIRST_COMPLETED)

        for pending_task in pending_tasks:
            pending_task.cancel()

            try:
                await pending_task

            except asyncio.CancelledError:
                pass

        if shutdown_poll_task in done_tasks and self._gui_stopped_event.is_set():

            connect_task.cancel()

            try:
                await connect_task

            except asyncio.CancelledError:
                pass

            raise asyncio.CancelledError()

        return connect_task.result()

    async def _run_connection(self):
        """Connect, stream VIDEO events, reconnect after drops, and honor shutdown."""

        had_successful_session = False

        while self._gui_stopped_event.is_set() is False:

            if had_successful_session:
                self.connection_progress.emit(
                    rdp_pipe.connection_progress.CONNECTION_STEP_RECONNECTING)

            connect_succeeded = False
            self._input_forwarder_future = None

            try:
                self._session = rdp_pipe.rdp_session_core.RdpAsyncSession(
                    self._connection_url,
                    self._video_width,
                    self._video_height,
                    color_depth=self._color_depth,
                    activity_stamp_filepath=self._activity_stamp_filepath)

                self._session.add_video_frame_callback(self._emit_video_frame)
                self._session.add_pointer_update_callback(self._emit_pointer_update)
                self._session.add_resolution_changed_callback(self._emit_resolution_changed)
                self._session.add_clipboard_text_callback(self._emit_clipboard_text)
                self._session.set_progress_callback(self._emit_connection_progress)

                await self._connect_session_unless_gui_stopped()
                connect_succeeded = True
                await self._session.drain_queued_pointer_updates()

                if self._session.display_caps_unavailable:
                    self.display_caps_unavailable.emit()

                self.session_ready.emit(self._session)

                event_loop = asyncio.get_event_loop()
                self._input_forwarder_future = event_loop.run_in_executor(
                    None,
                    self._input_forwarder,
                    event_loop)

                await self._session.run_until_stopped()

                if connect_succeeded and self._gui_stopped_event.is_set() is False:
                    disconnected_stderr = \
                        rdp_pipe.connection_error.format_session_disconnected_reconnecting_stderr(
                            self._connection_url)
                    sys.stderr.write(disconnected_stderr)

            except asyncio.CancelledError:
                return

            except Exception as error:

                if connect_succeeded:
                    session_ended_stderr = \
                        rdp_pipe.connection_error.format_session_ended_stderr(error)
                    sys.stderr.write(session_ended_stderr)

                elif self._gui_stopped_event.is_set() is False:
                    connection_failure_stderr = \
                        rdp_pipe.connection_error.format_connection_failure_stderr(
                            self._connection_url,
                            error)
                    sys.stderr.write(connection_failure_stderr)

            finally:
                if self._session is not None:

                    # Shield so a cancelled connect task still finishes terminate().

                    try:
                        session_stop = self._session.stop()
                        await asyncio.shield(session_stop)

                    except asyncio.CancelledError:
                        pass

                    self._session = None

                if self._input_forwarder_future is not None:
                    self._input_forwarder_future.cancel()
                    self._input_forwarder_future = None

                if connect_succeeded:
                    had_successful_session = True

            if self._gui_stopped_event.is_set():
                break

            await self._wait_before_reconnect()

    def _async_thread_main(self):
        """Create an asyncio loop and run the connection coroutine."""

        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)

        try:

            connection_coroutine = self._run_connection()
            self._connection_task = self._event_loop.create_task(connection_coroutine)

            try:
                self._event_loop.run_until_complete(self._connection_task)

            finally:
                close_event_loop_after_cancelling_pending_tasks(self._event_loop)

        finally:
            self._async_thread_finished_event.set()

    @PyQt6.QtCore.pyqtSlot()
    def start(self):
        """Start the asyncio worker thread."""

        self._async_thread = threading.Thread(
            target=self._async_thread_main,
            name="rdp-async-session",
            daemon=True)
        self._async_thread.start()

    @PyQt6.QtCore.pyqtSlot()
    def stop(self):
        """Signal shutdown and disconnect."""

        self._gui_stopped_event.set()

        # Cooperative terminate lets aardwolf readers finish. Cancelling the
        # connect task aborts that cleanup and leaves Queue.get waiters pending.

        if self._session is not None and self._event_loop is not None:

            if self._event_loop.is_running():

                session_stop = self._session.stop()
                self._stop_future = asyncio.run_coroutine_threadsafe(
                    session_stop,
                    self._event_loop)

                return

        if self._event_loop is not None and self._connection_task is not None:

            if self._connection_task.done() is False:
                self._event_loop.call_soon_threadsafe(self._connection_task.cancel)

    def force_async_thread_shutdown(
            self,
            timeout_seconds: float = ASYNC_THREAD_FORCE_SHUTDOWN_JOIN_SECONDS) -> bool:
        """Stop the asyncio loop and join the worker thread after a cooperative timeout."""

        if self._async_thread is None:
            return True

        if self._event_loop is not None and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)

        self._async_thread.join(timeout=timeout_seconds)

        if self._async_thread.is_alive():

            _LOGGER.warning(
                "RDP async worker thread did not exit after forced loop stop within {timeout_seconds} seconds".format(
                    timeout_seconds=timeout_seconds))

            return False

        return True

    def wait_for_shutdown(self, timeout_seconds: float) -> bool:
        """Block until the asyncio worker thread exits or timeout_seconds elapses."""

        if self._async_thread is None:
            return True

        self._async_thread.join(timeout=timeout_seconds)

        if self._async_thread.is_alive():

            _LOGGER.warning(
                "RDP session shutdown timed out after {timeout_seconds} seconds".format(
                    timeout_seconds=timeout_seconds))

            if self._connection_task is not None and self._event_loop is not None:

                if self._event_loop.is_running():
                    self._event_loop.call_soon_threadsafe(self._connection_task.cancel)

            return self.force_async_thread_shutdown()

        return True

    @PyQt6.QtCore.pyqtSlot(str)
    def push_local_clipboard_text(self, clipboard_text: str):
        """Schedule a local clipboard update for the remote RDPECLIP channel."""

        if self._session is None or self._event_loop is None:
            return

        if not self._event_loop.is_running():
            return

        clipboard_future = asyncio.run_coroutine_threadsafe(
            self._session.push_local_clipboard_text(clipboard_text),
            self._event_loop)
        clipboard_future.add_done_callback(self._log_clipboard_future_result)

    def _log_clipboard_future_result(self, clipboard_future):
        """Surface RDPECLIP failures scheduled from the Qt thread."""

        try:
            clipboard_future.result()

        except Exception:
            _LOGGER.exception("RDPECLIP local clipboard update failed")

    @PyQt6.QtCore.pyqtSlot(int, int)
    def request_remote_resolution(self, width: int, height: int):
        """Schedule an RDPDISP layout PDU on the asyncio loop."""

        if self._session is None or self._event_loop is None:
            return

        if not self._event_loop.is_running():
            return

        resize_future = asyncio.run_coroutine_threadsafe(
            self._session.request_remote_resolution(width, height),
            self._event_loop)
        resize_future.add_done_callback(self._log_resize_future_result)

    def _log_resize_future_result(self, resize_future):
        """Surface RDPDISP failures scheduled from the Qt thread."""

        try:
            resize_future.result()
        except Exception:
            _LOGGER.exception("RDPDISP resize request failed")
