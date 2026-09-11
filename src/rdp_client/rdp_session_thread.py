"""Qt thread bridge for asyncio RDP sessions."""

import asyncio
import logging
import queue
import threading
import traceback

import aardwolf.commons.queuedata
import PyQt6.QtCore

import rdp_client.rdp_connection


_LOGGER = logging.getLogger(__name__)

DISPLAY_CONTROL_CAPS_TIMEOUT_SECONDS = 10.0


class RdpVideoFrame:
    """Partial framebuffer update emitted to the Qt main thread."""

    def __init__(self, x_position, y_position, image, width, height):
        """Store rectangle metadata and a PIL image patch."""

        self.x_position = x_position
        self.y_position = y_position
        self.image = image
        self.width = width
        self.height = height


class RdpSessionWorker(PyQt6.QtCore.QObject):
    """Runs the aardwolf asyncio connection on a background Qt thread."""

    video_frame_ready = PyQt6.QtCore.pyqtSignal(object)
    connection_terminated = PyQt6.QtCore.pyqtSignal()
    resolution_changed = PyQt6.QtCore.pyqtSignal(int, int)
    display_caps_unavailable = PyQt6.QtCore.pyqtSignal()

    def __init__(self, parent=None):
        """Initialize worker state; call set_session before start."""

        super().__init__(parent)

        self._connection_url = None
        self._iosettings = None
        self._display_control_channel = None
        self._input_queue = None
        self._connection = None
        self._event_loop = None
        self._gui_stopped_event = threading.Event()
        self._async_thread = None
        self._connection_task = None

    def set_session(
            self,
            connection_url: str,
            iosettings,
            display_control_channel,
            input_queue: queue.Queue):

        """Bind URL, iosettings, RDPDISP channel, and the GUI input queue."""

        self._connection_url = connection_url
        self._iosettings = iosettings
        self._display_control_channel = display_control_channel
        self._input_queue = input_queue

    def _input_forwarder(self, event_loop: asyncio.AbstractEventLoop):
        """Forward GUI input queue items into the connection ext_in_queue."""

        while not self._connection.disconnected_evt.is_set():
            input_item = self._input_queue.get()
            event_loop.call_soon_threadsafe(
                self._connection.ext_in_queue.put_nowait,
                input_item)

            if input_item is None:
                break

    async def _run_connection(self):
        """Connect, stream VIDEO events, and honor shutdown."""

        input_forwarder_task = None

        try:
            connection_factory = \
                rdp_client.rdp_connection.RdpDesktopConnectionFactory.from_url(
                    self._connection_url,
                    self._iosettings)

            self._connection = connection_factory.get_connection(self._iosettings)
            self._connection.display_control_channel = self._display_control_channel

            self._connection.add_resolution_changed_listener(
                lambda width, height: self.resolution_changed.emit(width, height))

            connect_ok, connect_error = await self._connection.connect()
            if connect_error is not None:
                raise connect_error

            caps_available = await self._display_control_channel.wait_for_caps(
                DISPLAY_CONTROL_CAPS_TIMEOUT_SECONDS)

            if caps_available is False:
                self.display_caps_unavailable.emit()

            event_loop = asyncio.get_event_loop()
            input_forwarder_task = event_loop.run_in_executor(
                None,
                self._input_forwarder,
                event_loop)

            while not self._gui_stopped_event.is_set():
                output_item = await self._connection.ext_out_queue.get()
                if output_item is None:
                    return

                if output_item.type == aardwolf.commons.queuedata.RDPDATATYPE.VIDEO:
                    video_frame = RdpVideoFrame(
                        output_item.x,
                        output_item.y,
                        output_item.data,
                        output_item.width,
                        output_item.height)

                    if not self._gui_stopped_event.is_set():
                        self.video_frame_ready.emit(video_frame)
                    else:
                        return

        except asyncio.CancelledError:
            return

        except Exception:
            traceback.print_exc()

        finally:
            if self._connection is not None:
                await self._connection.terminate()

            if input_forwarder_task is not None:
                input_forwarder_task.cancel()

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

        if self._connection is not None and self._event_loop is not None:
            if self._event_loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._connection.terminate(),
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

        if self._connection is None or self._event_loop is None:
            return

        if not self._event_loop.is_running():
            return

        asyncio.run_coroutine_threadsafe(
            self._display_control_channel.request_resolution(width, height),
            self._event_loop)
