"""Qt thread bridge for asyncio RDP sessions."""

import asyncio
import logging
import sys
import queue
import threading
import traceback

import PyQt6.QtCore

import rdp_client.rdp_session_core
import rdp_client.trust_store


_LOGGER = logging.getLogger(__name__)


class RdpVideoFrame(rdp_client.rdp_session_core.RdpVideoFrame):
    """Partial framebuffer update emitted to the Qt main thread."""

    pass


class RdpSessionWorker(PyQt6.QtCore.QObject):
    """Runs RdpAsyncSession on a background Qt thread."""

    video_frame_ready = PyQt6.QtCore.pyqtSignal(object)
    connection_terminated = PyQt6.QtCore.pyqtSignal()
    resolution_changed = PyQt6.QtCore.pyqtSignal(int, int)
    display_caps_unavailable = PyQt6.QtCore.pyqtSignal()
    session_ready = PyQt6.QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        """Initialize worker state; call set_session before start."""

        super().__init__(parent)

        self._connection_url = None
        self._video_width = None
        self._video_height = None
        self._input_queue = None
        self._session: rdp_client.rdp_session_core.RdpAsyncSession | None = None
        self._event_loop = None
        self._gui_stopped_event = threading.Event()
        self._async_thread = None
        self._connection_task = None
        self._input_forwarder_future = None

    def set_session(
            self,
            connection_url: str,
            video_width: int,
            video_height: int,
            input_queue: queue.Queue):

        """Bind URL, video geometry, and the GUI input queue."""

        self._connection_url = connection_url
        self._video_width = video_width
        self._video_height = video_height
        self._input_queue = input_queue

    def get_session(self) -> rdp_client.rdp_session_core.RdpAsyncSession | None:
        """Return the active session after session_ready fires."""

        return self._session

    def _input_forwarder(self, event_loop: asyncio.AbstractEventLoop):
        """Forward GUI input queue items into the connection ext_in_queue."""

        while not self._session.connection.disconnected_evt.is_set():
            input_item = self._input_queue.get()
            event_loop.call_soon_threadsafe(
                self._session.connection.ext_in_queue.put_nowait,
                input_item)

            if input_item is None:
                break

    def _emit_video_frame(self, video_frame: rdp_client.rdp_session_core.RdpVideoFrame):
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

    def _emit_resolution_changed(self, width: int, height: int):
        """Bridge resolution changes to the Qt signal."""

        self.resolution_changed.emit(width, height)

    async def _run_connection(self):
        """Connect, stream VIDEO events, and honor shutdown."""

        try:
            self._session = rdp_client.rdp_session_core.RdpAsyncSession(
                self._connection_url,
                self._video_width,
                self._video_height)

            self._session.add_video_frame_callback(self._emit_video_frame)
            self._session.add_resolution_changed_callback(self._emit_resolution_changed)

            await self._session.connect()

            if self._session.display_caps_unavailable:
                self.display_caps_unavailable.emit()

            self.session_ready.emit(self._session)

            event_loop = asyncio.get_event_loop()
            self._input_forwarder_future = event_loop.run_in_executor(
                None,
                self._input_forwarder,
                event_loop)

            await self._session.run_until_stopped()

        except asyncio.CancelledError:
            return

        except rdp_client.trust_store.CertificateTrustMismatchError as trust_error:
            mismatch_stderr = \
                rdp_client.trust_store.format_certificate_trust_mismatch_stderr(
                    trust_error)
            sys.stderr.write(mismatch_stderr)

        except Exception:
            traceback.print_exc()

        finally:
            if self._session is not None:
                await self._session.stop()

            if self._input_forwarder_future is not None:
                self._input_forwarder_future.cancel()

            if not self._gui_stopped_event.is_set():
                self.connection_terminated.emit()

    def _async_thread_main(self):
        """Create an asyncio loop and run the connection coroutine."""

        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)

        try:
            self._connection_task = self._event_loop.create_task(self._run_connection())
            self._event_loop.run_until_complete(self._connection_task)
            self._event_loop.close()

        except Exception:
            traceback.print_exc()

    @PyQt6.QtCore.pyqtSlot()
    def start(self):
        """Start the asyncio worker thread."""

        self._async_thread = threading.Thread(target=self._async_thread_main)
        self._async_thread.start()

    @PyQt6.QtCore.pyqtSlot()
    def stop(self):
        """Signal shutdown and disconnect."""

        self._gui_stopped_event.set()

        if self._session is not None and self._event_loop is not None:
            if self._event_loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._session.stop(),
                        self._event_loop)
                except Exception:
                    pass

        if self._connection_task is not None and self._event_loop is not None:
            try:
                self._connection_task.cancel()
            except Exception:
                pass

    @PyQt6.QtCore.pyqtSlot(int, int)
    def request_remote_resolution(self, width: int, height: int):
        """Schedule an RDPDISP layout PDU on the asyncio loop."""

        if self._session is None or self._event_loop is None:
            return

        if not self._event_loop.is_running():
            return

        asyncio.run_coroutine_threadsafe(
            self._session.request_remote_resolution(width, height),
            self._event_loop)
