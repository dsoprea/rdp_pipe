"""Unit tests for Qt session canvas mouse forwarding."""

import queue

import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets
import aardwolf.commons.queuedata.constants
import pytest

import rdp_pipe.qt_session_window


@pytest.fixture(scope="module")
def qt_application():
    """Provide a single offscreen QApplication for Qt widget tests."""

    qt_application_instance = PyQt6.QtWidgets.QApplication.instance()

    if qt_application_instance is None:
        qt_application_instance = PyQt6.QtWidgets.QApplication([])

    return qt_application_instance


def _drain_mouse_messages(input_queue: queue.Queue) -> list:
    """Return every queued RDP_MOUSE message currently waiting."""

    messages = []

    while input_queue.empty() is False:
        messages.append(input_queue.get())

    return messages


def _configure_canvas_for_mouse_tests(canvas: rdp_pipe.qt_session_window.RdpCanvas):
    """Size the canvas so widget coordinates map 1:1 to the remote desktop."""

    canvas.resize(1280, 800)
    canvas.set_remote_dimensions(1280, 800)
    canvas.show()
    PyQt6.QtWidgets.QApplication.processEvents()


def _build_mouse_event(
        event_type: PyQt6.QtCore.QEvent.Type,
        widget_position: PyQt6.QtCore.QPoint,
        mouse_button: PyQt6.QtCore.Qt.MouseButton) -> PyQt6.QtGui.QMouseEvent:
    """Build a PyQt6 QMouseEvent for direct handler invocation in tests."""

    local_position = PyQt6.QtCore.QPointF(
        widget_position.x(),
        widget_position.y())

    return PyQt6.QtGui.QMouseEvent(
        event_type,
        local_position,
        mouse_button,
        mouse_button,
        PyQt6.QtCore.Qt.KeyboardModifier.NoModifier)


def test_double_click_forwards_four_messages(qt_application):
    """Double-click forwards down, up, second down, and final up."""

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_mouse_tests(canvas)

    widget_position = PyQt6.QtCore.QPoint(100, 100)
    left_button = PyQt6.QtCore.Qt.MouseButton.LeftButton

    canvas.mousePressEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonPress,
            widget_position,
            left_button))
    canvas.mouseReleaseEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonRelease,
            widget_position,
            left_button))
    canvas.mouseDoubleClickEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonDblClick,
            widget_position,
            left_button))
    canvas.mouseReleaseEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonRelease,
            widget_position,
            left_button))

    messages = _drain_mouse_messages(input_queue)

    assert len(messages) == 4
    assert messages[0].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT
    assert messages[0].is_pressed is True
    assert messages[1].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT
    assert messages[1].is_pressed is False
    assert messages[2].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT
    assert messages[2].is_pressed is True
    assert messages[3].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT
    assert messages[3].is_pressed is False


def test_context_menu_event_forwards_right_press_release(qt_application):
    """A mouse context-menu event enqueues a full right click when no press is pending."""

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_mouse_tests(canvas)

    context_menu_event = PyQt6.QtGui.QContextMenuEvent(
        PyQt6.QtGui.QContextMenuEvent.Reason.Mouse,
        PyQt6.QtCore.QPoint(100, 100))
    canvas.contextMenuEvent(context_menu_event)

    messages = _drain_mouse_messages(input_queue)

    assert len(messages) == 2
    assert messages[0].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT
    assert messages[0].is_pressed is True
    assert messages[1].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT
    assert messages[1].is_pressed is False


def test_context_menu_after_right_press_forwards_release_only(qt_application):
    """Linux-style right press plus context menu completes with a single release."""

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_mouse_tests(canvas)

    widget_position = PyQt6.QtCore.QPoint(100, 100)
    right_button = PyQt6.QtCore.Qt.MouseButton.RightButton

    canvas.mousePressEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonPress,
            widget_position,
            right_button))

    context_menu_event = PyQt6.QtGui.QContextMenuEvent(
        PyQt6.QtGui.QContextMenuEvent.Reason.Mouse,
        PyQt6.QtCore.QPoint(100, 100))
    canvas.contextMenuEvent(context_menu_event)

    messages = _drain_mouse_messages(input_queue)

    assert len(messages) == 2
    assert messages[0].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT
    assert messages[0].is_pressed is True
    assert messages[1].button == \
        aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT
    assert messages[1].is_pressed is False


def test_unmapped_button_does_not_crash(qt_application):
    """Extra mouse buttons are ignored instead of raising KeyError."""

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_mouse_tests(canvas)

    canvas.mousePressEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonPress,
            PyQt6.QtCore.QPoint(100, 100),
            PyQt6.QtCore.Qt.MouseButton.XButton1))

    messages = _drain_mouse_messages(input_queue)

    assert messages == []


def test_leave_event_restores_arrow_cursor_after_blank_cursor(qt_application):
    """Leaving the canvas for the native title bar restores a visible system arrow."""

    session_window = PyQt6.QtWidgets.QMainWindow()
    session_container = rdp_pipe.qt_session_window.RdpSessionContainer()
    session_window.setCentralWidget(session_container)
    canvas = session_container.canvas
    _configure_canvas_for_mouse_tests(canvas)
    session_window.show()
    PyQt6.QtWidgets.QApplication.processEvents()

    canvas.setCursor(PyQt6.QtCore.Qt.CursorShape.BlankCursor)
    session_container.setCursor(PyQt6.QtCore.Qt.CursorShape.BlankCursor)
    session_window.setCursor(PyQt6.QtCore.Qt.CursorShape.BlankCursor)
    canvas._cursor_overlay.set_pointer_position(PyQt6.QtCore.QPoint(100, 100))

    leave_event = PyQt6.QtCore.QEvent(PyQt6.QtCore.QEvent.Type.Leave)
    canvas.leaveEvent(leave_event)

    assert canvas.cursor().shape() == PyQt6.QtCore.Qt.CursorShape.ArrowCursor
    assert session_container.cursor().shape() == PyQt6.QtCore.Qt.CursorShape.ArrowCursor
    assert session_window.cursor().shape() == PyQt6.QtCore.Qt.CursorShape.ArrowCursor
    assert canvas._cursor_overlay.isVisible() is False
    assert canvas._pointer_inside_canvas is False


def test_mouse_debug_does_not_crash_on_press(qt_application, monkeypatch):
    """RDP_MOUSE_DEBUG logging uses PyQt6 pointer APIs, not QMouseEvent.source()."""

    monkeypatch.setenv("RDP_MOUSE_DEBUG", "1")

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_mouse_tests(canvas)

    canvas.mousePressEvent(
        _build_mouse_event(
            PyQt6.QtCore.QEvent.Type.MouseButtonPress,
            PyQt6.QtCore.QPoint(100, 100),
            PyQt6.QtCore.Qt.MouseButton.LeftButton))

    messages = _drain_mouse_messages(input_queue)

    assert len(messages) == 1
    assert messages[0].is_pressed is True
