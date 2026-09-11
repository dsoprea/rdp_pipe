"""PyQt6 session window with pointer-gated keyboard and RDPDISP resize."""

import logging
import queue
import sys

import aardwolf.commons.queuedata.constants
import aardwolf.commons.queuedata.mouse
import aardwolf.commons.queuedata.keyboard
import aardwolf.keyboard
import PIL.ImageQt
import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets

import rdp_client.command_socket
import rdp_client.connection_progress
import rdp_client.rdp_session_thread


_LOGGER = logging.getLogger(__name__)

CONNECTING_OVERLAY_PANEL_WIDTH = 420
CONNECTING_OVERLAY_PANEL_MARGIN = 24
CONNECTING_OVERLAY_PANEL_BACKGROUND = "#2b2b2b"

DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 800
RESIZE_DEBOUNCE_MILLISECONDS = 250


class RdpConnectingStepRow(PyQt6.QtWidgets.QWidget):
    """Single labeled row in the connecting progress modal."""

    def __init__(self, step_label: str, parent=None):
        """Build a row with a status glyph and step description."""

        super().__init__(parent)

        self.setAttribute(PyQt6.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "background-color: {panel_background};".format(
                panel_background=CONNECTING_OVERLAY_PANEL_BACKGROUND))

        self._status_label = PyQt6.QtWidgets.QLabel(self)
        self._description_label = PyQt6.QtWidgets.QLabel(step_label, self)

        row_layout = PyQt6.QtWidgets.QHBoxLayout(self)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        row_layout.addWidget(self._status_label)
        row_layout.addWidget(self._description_label, 1)

        self._status_label.setFixedWidth(18)
        self._description_label.setWordWrap(True)

        self.set_pending()

    def set_pending(self):
        """Show the step as not yet started."""

        self._status_label.setText("○")
        self._status_label.setStyleSheet(
            "background-color: transparent; color: #9aa0a6;")
        self._description_label.setStyleSheet(
            "background-color: transparent; color: #9aa0a6;")

    def set_active(self):
        """Highlight the step currently in progress."""

        self._status_label.setText("●")
        self._status_label.setStyleSheet(
            "background-color: transparent; color: #ffffff; font-weight: 600;")
        self._description_label.setStyleSheet(
            "background-color: transparent; color: #ffffff; font-weight: 600;")

    def set_complete(self):
        """Mark the step finished."""

        self._status_label.setText("✓")
        self._status_label.setStyleSheet(
            "background-color: transparent; color: #81c995;")
        self._description_label.setStyleSheet(
            "background-color: transparent; color: #81c995;")


class RdpConnectingOverlay(PyQt6.QtWidgets.QWidget):
    """Dimmed full-window overlay with a centered connecting progress modal."""

    def __init__(self, parent=None):
        """Create the overlay panel and step rows."""

        super().__init__(parent)

        self.setAttribute(PyQt6.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 170);")

        self._panel = PyQt6.QtWidgets.QFrame(self)
        self._panel.setObjectName("connectingPanel")
        self._panel.setStyleSheet(
            "#connectingPanel {{"
            "background-color: {panel_background};"
            "border: 1px solid #3c4043;"
            "border-radius: 12px;"
            "}}".format(panel_background=CONNECTING_OVERLAY_PANEL_BACKGROUND))

        self._title_label = PyQt6.QtWidgets.QLabel("Connecting", self._panel)
        self._title_label.setStyleSheet(
            "background-color: transparent;"
            "color: #ffffff; font-size: 18px; font-weight: 600;")

        self._step_rows_by_identifier: dict[str, RdpConnectingStepRow] = {}

        steps_layout = PyQt6.QtWidgets.QVBoxLayout()
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(8)

        for step_identifier in rdp_client.connection_progress.ORDERED_CONNECTION_STEPS:
            if step_identifier == rdp_client.connection_progress.CONNECTION_STEP_READY:
                continue

            step_label = rdp_client.connection_progress.get_connection_step_label(
                step_identifier)

            step_row = RdpConnectingStepRow(step_label, self._panel)
            self._step_rows_by_identifier[step_identifier] = step_row
            steps_layout.addWidget(step_row)

        self._progress_bar = PyQt6.QtWidgets.QProgressBar(self._panel)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setStyleSheet(
            "QProgressBar {"
            "background-color: #1f1f1f;"
            "border: none;"
            "border-radius: 2px;"
            "}"
            "QProgressBar::chunk {"
            "background-color: #8ab4f8;"
            "border-radius: 2px;"
            "}")

        panel_layout = PyQt6.QtWidgets.QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(
            CONNECTING_OVERLAY_PANEL_MARGIN,
            CONNECTING_OVERLAY_PANEL_MARGIN,
            CONNECTING_OVERLAY_PANEL_MARGIN,
            CONNECTING_OVERLAY_PANEL_MARGIN)
        panel_layout.setSpacing(16)
        panel_layout.addWidget(self._title_label)
        panel_layout.addLayout(steps_layout)
        panel_layout.addWidget(self._progress_bar)

        self._current_step_identifier = None
        self.set_progress_step(
            rdp_client.connection_progress.CONNECTION_STEP_PREPARING)

    def set_progress_step(self, step_identifier: str):
        """Advance the modal to the given connection step."""

        if step_identifier == rdp_client.connection_progress.CONNECTION_STEP_READY:
            self.hide()
            return

        step_index = rdp_client.connection_progress.get_connection_step_index(
            step_identifier)

        for listed_index, listed_step_identifier in enumerate(
                rdp_client.connection_progress.ORDERED_CONNECTION_STEPS):

            if listed_step_identifier == rdp_client.connection_progress.CONNECTION_STEP_READY:
                continue

            step_row = self._step_rows_by_identifier[listed_step_identifier]

            if listed_index < step_index:
                step_row.set_complete()

            elif listed_index == step_index:
                step_row.set_active()

            else:
                step_row.set_pending()

        self._current_step_identifier = step_identifier
        self.update()

    def resizeEvent(self, resize_event: PyQt6.QtGui.QResizeEvent):
        """Keep the modal panel centered over the dimmed overlay."""

        panel_width = CONNECTING_OVERLAY_PANEL_WIDTH
        panel_height = self._panel.sizeHint().height()
        origin_x = int((self.width() - panel_width) / 2)
        origin_y = int((self.height() - panel_height) / 2)

        if origin_x < 0:
            origin_x = 0
        if origin_y < 0:
            origin_y = 0

        self._panel.setGeometry(origin_x, origin_y, panel_width, panel_height)
        super().resizeEvent(resize_event)


class RdpSessionContainer(PyQt6.QtWidgets.QWidget):
    """Hosts the remote canvas with a connecting overlay stacked above it."""

    def __init__(self, parent=None):
        """Create the canvas and overlay children."""

        super().__init__(parent)

        self._canvas = RdpCanvas(self)
        self._connecting_overlay = RdpConnectingOverlay(self)

    @property
    def canvas(self) -> RdpCanvas:
        """Return the remote desktop canvas widget."""

        return self._canvas

    @property
    def connecting_overlay(self) -> RdpConnectingOverlay:
        """Return the connecting progress overlay."""

        return self._connecting_overlay

    def resizeEvent(self, resize_event: PyQt6.QtGui.QResizeEvent):
        """Resize children to fill the container."""

        container_rectangle = self.rect()
        self._canvas.setGeometry(container_rectangle)
        self._connecting_overlay.setGeometry(container_rectangle)
        super().resizeEvent(resize_event)


class RdpCanvas(PyQt6.QtWidgets.QLabel):
    """Remote desktop canvas with mouse forwarding and pointer-gated keyboard."""

    resize_requested = PyQt6.QtCore.pyqtSignal(int, int)

    def __init__(self, parent=None):
        """Create canvas state for framebuffer dimensions and input gating."""

        super().__init__(parent)

        self._remote_width = DEFAULT_WINDOW_WIDTH
        self._remote_height = DEFAULT_WINDOW_HEIGHT
        self._pointer_inside_canvas = False
        self._input_queue: queue.Queue | None = None
        self._resize_debounce_timer = PyQt6.QtCore.QTimer(self)
        self._resize_debounce_timer.setSingleShot(True)
        self._resize_debounce_timer.setInterval(RESIZE_DEBOUNCE_MILLISECONDS)
        self._resize_debounce_timer.timeout.connect(self._emit_debounced_resize)
        self._pending_resize_width = DEFAULT_WINDOW_WIDTH
        self._pending_resize_height = DEFAULT_WINDOW_HEIGHT

        self.setMouseTracking(True)
        self.setFocusPolicy(PyQt6.QtCore.Qt.FocusPolicy.StrongFocus)

        self._extended_key_map = {
            PyQt6.QtCore.Qt.Key.Key_End: "VK_END",
            PyQt6.QtCore.Qt.Key.Key_Down: "VK_DOWN",
            PyQt6.QtCore.Qt.Key.Key_PageDown: "VK_NEXT",
            PyQt6.QtCore.Qt.Key.Key_Insert: "VK_INSERT",
            PyQt6.QtCore.Qt.Key.Key_Delete: "VK_DELETE",
            PyQt6.QtCore.Qt.Key.Key_Print: "VK_SNAPSHOT",
            PyQt6.QtCore.Qt.Key.Key_Home: "VK_HOME",
            PyQt6.QtCore.Qt.Key.Key_Up: "VK_UP",
            PyQt6.QtCore.Qt.Key.Key_PageUp: "VK_PRIOR",
            PyQt6.QtCore.Qt.Key.Key_Left: "VK_LEFT",
            PyQt6.QtCore.Qt.Key.Key_Right: "VK_RIGHT",
            PyQt6.QtCore.Qt.Key.Key_Meta: "VK_LWIN",
            PyQt6.QtCore.Qt.Key.Key_Enter: "VK_RETURN",
            PyQt6.QtCore.Qt.Key.Key_Menu: "VK_LMENU",
            PyQt6.QtCore.Qt.Key.Key_Pause: "VK_PAUSE",
            PyQt6.QtCore.Qt.Key.Key_Slash: "VK_DIVIDE",
            PyQt6.QtCore.Qt.Key.Key_Period: "VK_DECIMAL",
        }

        self._mouse_button_map = {
            PyQt6.QtCore.Qt.MouseButton.LeftButton:
                aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT,
            PyQt6.QtCore.Qt.MouseButton.RightButton:
                aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT,
            PyQt6.QtCore.Qt.MouseButton.MiddleButton:
                aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_MIDDLE,
        }

    def set_input_queue(self, input_queue: queue.Queue):
        """Attach the queue used to forward mouse and keyboard events."""

        self._input_queue = input_queue

    def set_remote_dimensions(self, width: int, height: int):
        """Update remote resolution used for coordinate mapping and painting."""

        self._remote_width = width
        self._remote_height = height
        self.update()

    def _letterbox_origin(self) -> PyQt6.QtCore.QPoint:
        """Return top-left widget offset where the 1:1 remote image is drawn."""

        widget_width = self.width()
        widget_height = self.height()
        origin_x = int((widget_width - self._remote_width) / 2)
        origin_y = int((widget_height - self._remote_height) / 2)

        if origin_x < 0:
            origin_x = 0
        if origin_y < 0:
            origin_y = 0

        return PyQt6.QtCore.QPoint(origin_x, origin_y)

    def _map_widget_position_to_remote(
            self,
            widget_position: PyQt6.QtCore.QPoint) -> PyQt6.QtCore.QPoint | None:
        """Map widget coordinates to remote desktop coordinates."""

        origin = self._letterbox_origin()
        remote_x = widget_position.x() - origin.x()
        remote_y = widget_position.y() - origin.y()

        if remote_x < 0 or remote_y < 0:
            return None
        if remote_x >= self._remote_width or remote_y >= self._remote_height:
            return None

        return PyQt6.QtCore.QPoint(remote_x, remote_y)

    def _enqueue_mouse_event(
            self,
            mouse_event: PyQt6.QtGui.QMouseEvent,
            is_pressed: bool,
            is_hover: bool):

        if self._input_queue is None:
            return

        remote_position = self._map_widget_position_to_remote(mouse_event.position().toPoint())
        if remote_position is None and is_hover is False:
            return

        if remote_position is None:
            remote_position = PyQt6.QtCore.QPoint(0, 0)

        button = aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_HOVER
        if is_hover is False:
            button = self._mouse_button_map[mouse_event.button()]

        mouse_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
        mouse_message.xPos = remote_position.x()
        mouse_message.yPos = remote_position.y()
        mouse_message.button = button
        mouse_message.is_pressed = is_pressed if is_hover is False else False

        self._input_queue.put(mouse_message)

    def _enqueue_keyboard_event(self, key_event: PyQt6.QtGui.QKeyEvent, is_pressed: bool):
        """Forward scancode keyboard events when the pointer is inside the canvas."""

        if self._pointer_inside_canvas is False:
            return

        if self._input_queue is None:
            return

        modifiers = aardwolf.keyboard.VK_MODIFIERS(0)
        qt_modifiers = PyQt6.QtWidgets.QApplication.keyboardModifiers()

        if bool(qt_modifiers & PyQt6.QtCore.Qt.KeyboardModifier.ShiftModifier) \
                and key_event.key() != PyQt6.QtCore.Qt.Key.Key_Shift:
            modifiers = modifiers | aardwolf.keyboard.VK_MODIFIERS.VK_SHIFT

        if bool(qt_modifiers & PyQt6.QtCore.Qt.KeyboardModifier.ControlModifier) \
                and key_event.key() != PyQt6.QtCore.Qt.Key.Key_Control:
            modifiers = modifiers | aardwolf.keyboard.VK_MODIFIERS.VK_CONTROL

        if bool(qt_modifiers & PyQt6.QtCore.Qt.KeyboardModifier.AltModifier) \
                and key_event.key() != PyQt6.QtCore.Qt.Key.Key_Alt:
            modifiers = modifiers | aardwolf.keyboard.VK_MODIFIERS.VK_MENU

        keyboard_message = aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_SCANCODE()
        keyboard_message.keyCode = key_event.nativeScanCode()
        keyboard_message.is_pressed = is_pressed

        if sys.platform == "linux":
            keyboard_message.keyCode = keyboard_message.keyCode - 8

        keyboard_message.modifiers = modifiers

        if key_event.key() in self._extended_key_map.keys():
            keyboard_message.vk_code = self._extended_key_map[key_event.key()]

        self._input_queue.put(keyboard_message)

    def enterEvent(self, enter_event: PyQt6.QtGui.QEnterEvent):
        """Track pointer entry and focus the canvas for keyboard input."""

        self._pointer_inside_canvas = True
        self.setFocus(PyQt6.QtCore.Qt.FocusReason.MouseFocusReason)
        super().enterEvent(enter_event)

    def leaveEvent(self, leave_event: PyQt6.QtCore.QEvent):
        """Stop forwarding keyboard events when the pointer leaves."""

        self._pointer_inside_canvas = False
        super().leaveEvent(leave_event)

    def mousePressEvent(self, mouse_event: PyQt6.QtGui.QMouseEvent):
        """Forward mouse press to the RDP session."""

        self._enqueue_mouse_event(mouse_event, True, False)
        super().mousePressEvent(mouse_event)

    def mouseReleaseEvent(self, mouse_event: PyQt6.QtGui.QMouseEvent):
        """Forward mouse release to the RDP session."""

        self._enqueue_mouse_event(mouse_event, False, False)
        super().mouseReleaseEvent(mouse_event)

    def mouseMoveEvent(self, mouse_event: PyQt6.QtGui.QMouseEvent):
        """Forward mouse movement while tracking is enabled."""

        self._enqueue_mouse_event(mouse_event, False, True)
        super().mouseMoveEvent(mouse_event)

    def wheelEvent(self, wheel_event: PyQt6.QtGui.QWheelEvent):
        """Forward wheel events as vertical mouse wheel buttons."""

        if self._input_queue is None:
            return

        remote_position = self._map_widget_position_to_remote(
            wheel_event.position().toPoint())

        if remote_position is None:
            return

        delta = wheel_event.angleDelta().y()
        if delta == 0:
            return

        if delta > 0:
            button = aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP
        else:
            button = aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_WHEEL_DOWN

        press_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
        press_message.xPos = remote_position.x()
        press_message.yPos = remote_position.y()
        press_message.button = button
        press_message.is_pressed = True
        self._input_queue.put(press_message)

        release_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
        release_message.xPos = remote_position.x()
        release_message.yPos = remote_position.y()
        release_message.button = button
        release_message.is_pressed = False
        self._input_queue.put(release_message)

        super().wheelEvent(wheel_event)

    def keyPressEvent(self, key_event: PyQt6.QtGui.QKeyEvent):
        """Forward key press when the pointer is inside the canvas."""

        self._enqueue_keyboard_event(key_event, True)
        super().keyPressEvent(key_event)

    def keyReleaseEvent(self, key_event: PyQt6.QtGui.QKeyEvent):
        """Forward key release when the pointer is inside the canvas."""

        self._enqueue_keyboard_event(key_event, False)
        super().keyReleaseEvent(key_event)

    def resizeEvent(self, resize_event: PyQt6.QtGui.QResizeEvent):
        """Debounce widget resize and request matching remote resolution."""

        client_size = self.size()
        self._pending_resize_width = client_size.width()
        self._pending_resize_height = client_size.height()
        self._resize_debounce_timer.start()
        super().resizeEvent(resize_event)

    def _emit_debounced_resize(self):
        """Emit resize_requested after debounce settles."""

        self.resize_requested.emit(
            self._pending_resize_width,
            self._pending_resize_height)


class RdpSessionWindow(PyQt6.QtWidgets.QMainWindow):
    """Top-level window hosting the RDP canvas and background session worker."""

    def __init__(
            self,
            connection_url: str,
            video_width: int,
            video_height: int,
            color_depth: int = 32,
            command_socket_path: str | None = None,
            activity_stamp_filepath: str | None = None):

        """Build UI, iosettings, and the asyncio/Qt bridge."""

        super().__init__()

        self._connection_url = connection_url
        self._input_queue = queue.Queue()
        self._display_caps_warning_shown = False
        self._command_socket_path = command_socket_path
        self._command_server = None
        self._video_width = video_width
        self._video_height = video_height

        self._frame_buffer = PyQt6.QtGui.QImage(
            video_width,
            video_height,
            PyQt6.QtGui.QImage.Format.Format_RGB32)

        self.setWindowTitle("RDP session")
        self.resize(video_width, video_height)

        self._session_container = RdpSessionContainer(self)
        self._canvas = self._session_container.canvas
        self._connecting_overlay = self._session_container.connecting_overlay

        self._canvas.set_input_queue(self._input_queue)
        self._canvas.set_remote_dimensions(video_width, video_height)
        self._canvas.resize_requested.connect(self._handle_canvas_resize_requested)

        self.setCentralWidget(self._session_container)

        self._worker = rdp_client.rdp_session_thread.RdpSessionWorker()
        self._worker.set_session(
            connection_url,
            video_width,
            video_height,
            self._input_queue,
            color_depth=color_depth,
            activity_stamp_filepath=activity_stamp_filepath)

        self._worker_thread = PyQt6.QtCore.QThread()
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.start)
        self._worker.video_frame_ready.connect(self._handle_video_frame)
        self._worker.connection_terminated.connect(self._handle_connection_terminated)
        self._worker.resolution_changed.connect(self._handle_resolution_changed)
        self._worker.display_caps_unavailable.connect(self._handle_display_caps_unavailable)
        self._worker.session_ready.connect(self._handle_session_ready)
        self._worker.connection_progress.connect(self._handle_connection_progress)

        PyQt6.QtWidgets.QApplication.instance().aboutToQuit.connect(self._worker_thread.quit)
        self._worker_thread.start()

    def _handle_connection_progress(self, step_identifier: str):
        """Update the connecting overlay as the background session advances."""

        self._connecting_overlay.set_progress_step(step_identifier)

    def _handle_session_ready(self, session):
        """Start the optional command socket after RDP connect succeeds."""

        self._connecting_overlay.set_progress_step(
            rdp_client.connection_progress.CONNECTION_STEP_READY)

        if self._command_socket_path is None:
            return

        self._command_server = rdp_client.command_socket.CommandSocketServer(
            self._command_socket_path,
            session)

        self._command_server.start()

    def _handle_video_frame(self, video_frame: rdp_client.rdp_session_thread.RdpVideoFrame):
        """Blit a partial rectangle into the local QImage buffer."""

        session = self._worker.get_session()
        video_width = self._video_width
        video_height = self._video_height

        if session is not None:
            video_width = session.iosettings.video_width
            video_height = session.iosettings.video_height

        if self._frame_buffer.width() != video_width \
                or self._frame_buffer.height() != video_height:

            self._frame_buffer = PyQt6.QtGui.QImage(
                video_width,
                video_height,
                PyQt6.QtGui.QImage.Format.Format_RGB32)

        patch_image = PIL.ImageQt.ImageQt(video_frame.image)

        painter = PyQt6.QtGui.QPainter(self._frame_buffer)
        painter.drawImage(
            video_frame.x_position,
            video_frame.y_position,
            patch_image,
            0,
            0,
            video_frame.width,
            video_frame.height)
        painter.end()

        pixmap = PyQt6.QtGui.QPixmap.fromImage(self._frame_buffer)
        self._canvas.setPixmap(pixmap)
        self._canvas.setAlignment(PyQt6.QtCore.Qt.AlignmentFlag.AlignCenter)

    def _handle_resolution_changed(self, width: int, height: int):
        """Resize local buffers when the server changes session geometry."""

        self._frame_buffer = PyQt6.QtGui.QImage(
            width,
            height,
            PyQt6.QtGui.QImage.Format.Format_RGB32)

        self._canvas.set_remote_dimensions(width, height)

    def _handle_display_caps_unavailable(self):
        """Record when RDPDISP caps never arrive (core logs once)."""

        self._display_caps_warning_shown = True

    def _handle_canvas_resize_requested(self, width: int, height: int):
        """Forward debounced canvas size to the RDPDISP worker."""

        self._worker.request_remote_resolution(width, height)

    def _handle_connection_terminated(self):
        """Close the window when the background session ends."""

        self.close()

    def closeEvent(self, close_event: PyQt6.QtGui.QCloseEvent):
        """Shut down input forwarding and the worker thread."""

        if self._command_server is not None:
            self._command_server.stop()

        self._input_queue.put(None)
        self._worker.stop()
        self._worker_thread.quit()
        self._worker_thread.wait(2000)
        super().closeEvent(close_event)
