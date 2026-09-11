"""PyQt6 session window with pointer-gated keyboard and RDPDISP resize."""

import logging
import queue
import sys
import time

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
import rdp_client.connection_url
import rdp_client.pointer_debug
import rdp_client.pointer_update
import rdp_client.rdp_session_thread


_LOGGER = logging.getLogger(__name__)

CONNECTING_OVERLAY_PANEL_WIDTH = 420
CONNECTING_OVERLAY_PANEL_MARGIN = 24
CONNECTING_OVERLAY_PANEL_BACKGROUND = "#2b2b2b"

DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 800
SESSION_SHUTDOWN_TIMEOUT_SECONDS = 5.0
RESIZE_DEBOUNCE_MILLISECONDS = 250
MOUSE_POINTER_DEBUG_INTERVAL_SECONDS = 0.5
DEFAULT_SUPPRESS_SECONDS_AFTER_BITMAP = 0.1


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


def build_cursor_pixmap_from_rgba_image(image: PIL.Image.Image) -> PyQt6.QtGui.QPixmap:
    """Build a Qt pixmap with alpha suitable for overlay cursor painting."""

    qimage = PIL.ImageQt.ImageQt(image.convert("RGBA"))

    return PyQt6.QtGui.QPixmap.fromImage(qimage)


class RdpRemoteCursorOverlay(PyQt6.QtWidgets.QWidget):
    """Transparent layer that paints the remote pointer above the framebuffer."""

    def __init__(self, parent=None):
        """Create an initially hidden overlay."""

        super().__init__(parent)

        self.setAttribute(PyQt6.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(PyQt6.QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(PyQt6.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._cursor_pixmap: PyQt6.QtGui.QPixmap | None = None
        self._cursor_hotspot_x = 0
        self._cursor_hotspot_y = 0
        self._pointer_position: PyQt6.QtCore.QPoint | None = None

    def clear_cursor(self):
        """Remove the painted remote pointer."""

        self._cursor_pixmap = None
        self._pointer_position = None
        self.hide()
        self.update()

    def set_cursor_pixmap(
            self,
            cursor_pixmap: PyQt6.QtGui.QPixmap | None,
            hotspot_x: int,
            hotspot_y: int):

        """Store a remote pointer pixmap and hotspot for painting."""

        if cursor_pixmap is None or cursor_pixmap.isNull():
            self.clear_cursor()

            return

        self._cursor_pixmap = cursor_pixmap
        self._cursor_hotspot_x = hotspot_x
        self._cursor_hotspot_y = hotspot_y
        self.show()
        self.raise_()
        self.update()

    def set_pointer_position(self, pointer_position: PyQt6.QtCore.QPoint | None):
        """Move the painted remote pointer to a widget-local position."""

        self._pointer_position = pointer_position

        if self._cursor_pixmap is not None and pointer_position is not None:
            self.update()

    def paintEvent(self, paint_event: PyQt6.QtGui.QPaintEvent):
        """Draw the remote pointer bitmap at the tracked widget position."""

        if self._cursor_pixmap is None or self._pointer_position is None:
            return

        painter = PyQt6.QtGui.QPainter(self)
        painter.setCompositionMode(
            PyQt6.QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
        cursor_x = self._pointer_position.x() - self._cursor_hotspot_x
        cursor_y = self._pointer_position.y() - self._cursor_hotspot_y
        painter.drawPixmap(cursor_x, cursor_y, self._cursor_pixmap)
        painter.end()


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
        self._bitmap_pointer_update: rdp_client.pointer_update.RdpPointerUpdate | None = None
        self._last_pointer_widget_position: PyQt6.QtCore.QPoint | None = None
        self._suppress_default_pointer_until: float = 0.0
        self._last_mouse_pointer_debug_at: float = 0.0
        self._cursor_pixmap_cache_key: tuple[bytes, int, int] | None = None
        self._cursor_pixmap_cached: PyQt6.QtGui.QPixmap | None = None
        self._cursor_overlay = RdpRemoteCursorOverlay(self)
        self._cursor_overlay.hide()
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

    def reset_remote_pointer_state(self):
        """Clear cached server pointer shapes at session start."""

        self._suppress_default_pointer_until = 0.0
        self._bitmap_pointer_update = None
        self._sync_remote_cursor_display()

    def send_session_ready_pointer_hover(self):
        """Forward an initial hover so server hit-testing matches other RDP clients."""

        if self._last_pointer_widget_position is not None:
            widget_position = self._last_pointer_widget_position
        else:
            widget_position = PyQt6.QtCore.QPoint(
                self.width() // 2,
                self.height() // 2)

        self._enqueue_hover_at_widget_position(widget_position)

        if rdp_client.pointer_debug.is_pointer_debug_enabled():
            remote_position = self._map_widget_position_to_remote(widget_position)
            remote_detail = "none"

            if remote_position is not None:
                remote_detail = "({remote_x}, {remote_y})".format(
                    remote_x=remote_position.x(),
                    remote_y=remote_position.y())

            rdp_client.pointer_debug.write_pointer_debug(
                "pointer display: session-ready hover widget=({widget_x}, {widget_y}) remote={remote_detail}".format(
                    widget_x=widget_position.x(),
                    widget_y=widget_position.y(),
                    remote_detail=remote_detail))

    def _widget_position_from_point(
            self,
            widget_position: PyQt6.QtCore.QPointF) -> PyQt6.QtCore.QPoint:
        """Round a widget-local QPointF to integer coordinates for RDP mapping."""

        return PyQt6.QtCore.QPoint(
            int(round(widget_position.x())),
            int(round(widget_position.y())))

    def _enqueue_hover_at_widget_position(self, widget_position: PyQt6.QtCore.QPoint):
        """Forward a hover event for a widget-local pointer position."""

        if self._input_queue is None:
            return

        remote_position = self._map_widget_position_to_remote(widget_position)
        if remote_position is None:
            return

        mouse_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
        mouse_message.xPos = remote_position.x()
        mouse_message.yPos = remote_position.y()
        mouse_message.button = \
            aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_HOVER
        mouse_message.is_pressed = False

        self._input_queue.put(mouse_message)

    def _remote_framebuffer_size(self) -> tuple[int, int]:
        """Return the painted pixmap size used for mouse coordinate mapping."""

        pixmap = self.pixmap()

        if pixmap is not None and pixmap.isNull() is False:
            return pixmap.width(), pixmap.height()

        return self._remote_width, self._remote_height

    def _letterbox_origin(self) -> PyQt6.QtCore.QPoint:
        """Return the widget offset of the remote framebuffer's top-left corner."""

        framebuffer_width, framebuffer_height = self._remote_framebuffer_size()
        widget_width = self.width()
        widget_height = self.height()
        origin_x = int((widget_width - framebuffer_width) / 2)
        origin_y = int((widget_height - framebuffer_height) / 2)

        return PyQt6.QtCore.QPoint(origin_x, origin_y)

    def _map_widget_position_to_remote(
            self,
            widget_position: PyQt6.QtCore.QPoint) -> PyQt6.QtCore.QPoint | None:
        """Map widget coordinates to remote desktop coordinates."""

        framebuffer_width, framebuffer_height = self._remote_framebuffer_size()
        origin = self._letterbox_origin()
        remote_x = widget_position.x() - origin.x()
        remote_y = widget_position.y() - origin.y()

        if remote_x < 0 or remote_y < 0:
            return None

        # Clamp bottom/right edge hovers so a 1px overshoot still hits the resize band.
        if remote_x >= framebuffer_width:
            remote_x = framebuffer_width - 1

        if remote_y >= framebuffer_height:
            remote_y = framebuffer_height - 1

        return PyQt6.QtCore.QPoint(remote_x, remote_y)

    def _enqueue_mouse_event(
            self,
            mouse_event: PyQt6.QtGui.QMouseEvent,
            is_pressed: bool,
            is_hover: bool):

        if self._input_queue is None:
            return

        remote_position = self._map_widget_position_to_remote(
            self._widget_position_from_point(mouse_event.position()))
        if remote_position is None:
            return

        button = aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_HOVER
        if is_hover is False:
            button = self._mouse_button_map[mouse_event.button()]

        mouse_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
        mouse_message.xPos = remote_position.x()
        mouse_message.yPos = remote_position.y()
        mouse_message.button = button
        mouse_message.is_pressed = is_pressed if is_hover is False else False

        self._input_queue.put(mouse_message)

        if is_hover and rdp_client.pointer_debug.is_pointer_debug_enabled():
            debug_now = time.monotonic()
            if debug_now - self._last_mouse_pointer_debug_at >= MOUSE_POINTER_DEBUG_INTERVAL_SECONDS:
                self._last_mouse_pointer_debug_at = debug_now
                framebuffer_width, framebuffer_height = self._remote_framebuffer_size()
                origin = self._letterbox_origin()
                pixmap = self.pixmap()
                pixmap_device_pixel_ratio = 0.0

                if pixmap is not None and pixmap.isNull() is False:
                    pixmap_device_pixel_ratio = pixmap.devicePixelRatio()

                rdp_client.pointer_debug.write_pointer_debug(
                    "mouse hover forwarded remote=({remote_x}, {remote_y}) widget=({widget_width}, {widget_height}) "
                    "framebuffer=({framebuffer_width}, {framebuffer_height}) origin=({origin_x}, {origin_y}) "
                    "pixmap_dpr={pixmap_device_pixel_ratio} canvas_dpr={canvas_device_pixel_ratio}".format(
                        remote_x=remote_position.x(),
                        remote_y=remote_position.y(),
                        widget_width=self.width(),
                        widget_height=self.height(),
                        framebuffer_width=framebuffer_width,
                        framebuffer_height=framebuffer_height,
                        origin_x=origin.x(),
                        origin_y=origin.y(),
                        pixmap_device_pixel_ratio=pixmap_device_pixel_ratio,
                        canvas_device_pixel_ratio=self.devicePixelRatioF()))

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
        widget_position = self._widget_position_from_point(enter_event.position())
        self._last_pointer_widget_position = widget_position
        self._cursor_overlay.set_pointer_position(widget_position)
        self._enqueue_hover_at_widget_position(widget_position)
        self._sync_remote_cursor_display()
        super().enterEvent(enter_event)

    def leaveEvent(self, leave_event: PyQt6.QtCore.QEvent):
        """Stop forwarding keyboard events when the pointer leaves."""

        self._pointer_inside_canvas = False
        self._last_pointer_widget_position = None
        self.unsetCursor()
        self._cursor_overlay.set_pointer_position(None)
        super().leaveEvent(leave_event)

    def apply_pointer_update(self, pointer_update: rdp_client.pointer_update.RdpPointerUpdate):
        """Apply a server pointer update to the canvas cursor overlay."""

        if pointer_update.kind == rdp_client.pointer_update.RdpPointerUpdateKind.BITMAP:
            if pointer_update.image is None:
                return

            self._suppress_default_pointer_until = \
                time.monotonic() + DEFAULT_SUPPRESS_SECONDS_AFTER_BITMAP
            self._bitmap_pointer_update = pointer_update

            if self._pointer_inside_canvas:
                self._sync_remote_cursor_display()
                self.raise_cursor_overlay()
                self._write_pointer_apply_debug(pointer_update, applied=True)

                return

            self._write_pointer_apply_debug(pointer_update, applied=False)

            return

        if self._pointer_inside_canvas is False:
            if rdp_client.pointer_debug.is_pointer_debug_enabled():
                rdp_client.pointer_debug.write_pointer_debug(
                    "pointer apply: {kind} ignored pointer outside canvas".format(
                        kind=pointer_update.kind.value))

            return

        if pointer_update.kind == rdp_client.pointer_update.RdpPointerUpdateKind.DEFAULT:
            if time.monotonic() < self._suppress_default_pointer_until:
                rdp_client.pointer_debug.write_pointer_debug(
                    "pointer apply: default suppressed (paired with prior bitmap)")

                return

            self._bitmap_pointer_update = None
            self._sync_remote_cursor_display()
            self._write_pointer_apply_debug(pointer_update, applied=True)

            return

        if pointer_update.kind == rdp_client.pointer_update.RdpPointerUpdateKind.HIDDEN:
            self._suppress_default_pointer_until = 0.0
            self._bitmap_pointer_update = None
            self._cursor_overlay.clear_cursor()
            self.setCursor(PyQt6.QtCore.Qt.CursorShape.BlankCursor)

            return

    def _write_pointer_apply_debug(
            self,
            pointer_update: rdp_client.pointer_update.RdpPointerUpdate,
            applied: bool):

        if not rdp_client.pointer_debug.is_pointer_debug_enabled():
            return

        if pointer_update.kind == rdp_client.pointer_update.RdpPointerUpdateKind.BITMAP:
            image = pointer_update.image
            visible_pixel_count = 0

            if image is not None:
                visible_pixel_count = \
                    rdp_client.pointer_update.count_pointer_image_visible_pixels(image)

            rdp_client.pointer_debug.write_pointer_debug(
                "pointer apply: bitmap {width}x{height} xor_bpp={xor_bpp} cache_index={cache_index} hotspot=({hotspot_x}, {hotspot_y}) visible_pixels={visible_pixel_count} applied={applied} inside={inside}".format(
                    width=image.width if image is not None else 0,
                    height=image.height if image is not None else 0,
                    xor_bpp=pointer_update.xor_bits_per_pixel,
                    cache_index=pointer_update.cache_index,
                    hotspot_x=pointer_update.hotspot_x,
                    hotspot_y=pointer_update.hotspot_y,
                    visible_pixel_count=visible_pixel_count,
                    applied=applied,
                    inside=self._pointer_inside_canvas))

            return

        rdp_client.pointer_debug.write_pointer_debug(
            "pointer apply: {kind} applied={applied} inside={inside}".format(
                kind=pointer_update.kind.value,
                applied=applied,
                inside=self._pointer_inside_canvas))

    def raise_cursor_overlay(self):
        """Keep the remote pointer layer above the framebuffer pixmap."""

        self._cursor_overlay.raise_()

    def _get_cursor_pixmap_for_image(
            self,
            image: PIL.Image.Image,
            hotspot_x: int,
            hotspot_y: int) -> PyQt6.QtGui.QPixmap:
        """Return a cached Qt pixmap for a decoded pointer image."""

        cache_key = (image.tobytes(), hotspot_x, hotspot_y)

        if cache_key == self._cursor_pixmap_cache_key and self._cursor_pixmap_cached is not None:
            return self._cursor_pixmap_cached

        cursor_pixmap = build_cursor_pixmap_from_rgba_image(image)
        self._cursor_pixmap_cache_key = cache_key
        self._cursor_pixmap_cached = cursor_pixmap

        return cursor_pixmap

    def _sync_remote_cursor_display(self):
        """Paint the remote pointer overlay and hide the local mouse cursor."""

        if self._pointer_inside_canvas is False:
            return

        pointer_update = self._bitmap_pointer_update

        if pointer_update is None or pointer_update.image is None:
            self.unsetCursor()
            self._cursor_overlay.clear_cursor()

            return

        if not rdp_client.pointer_update.pointer_image_has_visible_pixels(pointer_update.image):
            self.unsetCursor()
            self._cursor_overlay.clear_cursor()
            rdp_client.pointer_debug.write_pointer_debug(
                "pointer sync: bitmap has no visible pixels; using local arrow")

            return

        cursor_pixmap = self._get_cursor_pixmap_for_image(
            pointer_update.image,
            pointer_update.hotspot_x,
            pointer_update.hotspot_y)

        self._cursor_overlay.set_cursor_pixmap(
            cursor_pixmap,
            pointer_update.hotspot_x,
            pointer_update.hotspot_y)

        if self._last_pointer_widget_position is not None:
            self._cursor_overlay.set_pointer_position(self._last_pointer_widget_position)

        self.setCursor(PyQt6.QtCore.Qt.CursorShape.BlankCursor)

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

        pointer_position = self._widget_position_from_point(mouse_event.position())
        self._last_pointer_widget_position = pointer_position
        self._cursor_overlay.set_pointer_position(pointer_position)

        if self._bitmap_pointer_update is not None and self._bitmap_pointer_update.image is not None:
            self.setCursor(PyQt6.QtCore.Qt.CursorShape.BlankCursor)

        self._enqueue_mouse_event(mouse_event, False, True)
        super().mouseMoveEvent(mouse_event)

    def wheelEvent(self, wheel_event: PyQt6.QtGui.QWheelEvent):
        """Forward wheel events as vertical mouse wheel buttons."""

        if self._input_queue is None:
            return

        remote_position = self._map_widget_position_to_remote(
            self._widget_position_from_point(wheel_event.position()))

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
        """Keep the pointer overlay sized and debounce remote resize requests."""

        self._cursor_overlay.setGeometry(self.rect())
        self._cursor_overlay.raise_()

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
        self._shutdown_started = False
        self._video_width = video_width
        self._video_height = video_height

        self._frame_buffer = PyQt6.QtGui.QImage(
            video_width,
            video_height,
            PyQt6.QtGui.QImage.Format.Format_RGB32)

        self.setWindowTitle(
            rdp_client.connection_url.build_session_window_title(connection_url))
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
        self._worker.pointer_update_ready.connect(
            self._handle_pointer_update,
            PyQt6.QtCore.Qt.ConnectionType.QueuedConnection)
        self._worker.connection_terminated.connect(self._handle_connection_terminated)
        self._worker.resolution_changed.connect(self._handle_resolution_changed)
        self._worker.display_caps_unavailable.connect(self._handle_display_caps_unavailable)
        self._worker.session_ready.connect(self._handle_session_ready)
        self._worker.connection_progress.connect(self._handle_connection_progress)

        PyQt6.QtWidgets.QApplication.instance().aboutToQuit.connect(
            self._handle_application_about_to_quit)
        self._worker_thread.start()

    def _handle_connection_progress(self, step_identifier: str):
        """Update the connecting overlay as the background session advances."""

        self._connecting_overlay.set_progress_step(step_identifier)

    def _handle_session_ready(self, session):
        """Start the optional command socket after RDP connect succeeds."""

        self._connecting_overlay.set_progress_step(
            rdp_client.connection_progress.CONNECTION_STEP_READY)

        if session.connection is not None:
            rdp_client.pointer_debug.write_pointer_session_summary(
                session.connection._pointer_cache,
                session.connection._pointer_pdu_count_by_update_code)

            cached_bitmap_update = \
                session.connection._pointer_cache.get_last_stored_bitmap_update()

            if cached_bitmap_update is not None:
                self._canvas.apply_pointer_update(cached_bitmap_update)
            else:
                self._canvas.reset_remote_pointer_state()
        else:
            self._canvas.reset_remote_pointer_state()

        if self._command_socket_path is None:
            return

        self._command_server = rdp_client.command_socket.CommandSocketServer(
            self._command_socket_path,
            session)

        self._command_server.start()

    def _handle_pointer_update(self, pointer_update: rdp_client.pointer_update.RdpPointerUpdate):
        """Apply a server pointer update to the session canvas."""

        self._canvas.apply_pointer_update(pointer_update)

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

        self._frame_buffer.setDevicePixelRatio(1.0)
        pixmap = PyQt6.QtGui.QPixmap.fromImage(self._frame_buffer)
        pixmap.setDevicePixelRatio(1.0)
        self._canvas.setPixmap(pixmap)
        self._canvas.setAlignment(PyQt6.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._canvas.set_remote_dimensions(video_width, video_height)
        self._canvas.raise_cursor_overlay()

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

    def _handle_application_about_to_quit(self):
        """Tear down the RDP session when the Qt application exits."""

        self._shutdown_session_resources()

    def _shutdown_session_resources(self):
        """Stop automation, disconnect RDP, and join background worker threads."""

        if self._shutdown_started:
            return

        self._shutdown_started = True

        if self._command_server is not None:
            self._command_server.stop()

        self._input_queue.put(None)
        self._worker.stop()
        self._worker.wait_for_shutdown(SESSION_SHUTDOWN_TIMEOUT_SECONDS)
        self._worker_thread.quit()
        self._worker_thread.wait(2000)

    def closeEvent(self, close_event: PyQt6.QtGui.QCloseEvent):
        """Shut down input forwarding and wait for the RDP session to disconnect."""

        self._shutdown_session_resources()
        super().closeEvent(close_event)
