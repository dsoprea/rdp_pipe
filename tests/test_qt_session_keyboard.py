"""Unit tests for Qt session canvas keyboard forwarding and focus recovery."""

import queue
import unittest.mock

import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets
import aardwolf.commons.queuedata.keyboard
import pytest

import rdp_pipe.qt_session_window


@pytest.fixture(scope="module")
def qt_application():
    """Provide a single offscreen QApplication for Qt widget tests."""

    qt_application_instance = PyQt6.QtWidgets.QApplication.instance()

    if qt_application_instance is None:
        qt_application_instance = PyQt6.QtWidgets.QApplication([])

    return qt_application_instance


def _drain_keyboard_messages(input_queue: queue.Queue) -> list:
    """Return every queued keyboard scancode message currently waiting."""

    messages = []

    while input_queue.empty() is False:
        queued_item = input_queue.get()

        if isinstance(queued_item, aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_SCANCODE):
            messages.append(queued_item)

    return messages


def _configure_canvas_for_keyboard_tests(canvas: rdp_pipe.qt_session_window.RdpCanvas):
    """Size the canvas and mark the pointer inside for keyboard tests."""

    canvas.resize(1280, 800)
    canvas.set_remote_dimensions(1280, 800)
    canvas.show()
    canvas._pointer_inside_canvas = True
    PyQt6.QtWidgets.QApplication.processEvents()


def _build_mouse_press_event(
        widget_position: PyQt6.QtCore.QPoint) -> PyQt6.QtGui.QMouseEvent:
    """Build a left-button press event for direct handler invocation."""

    local_position = PyQt6.QtCore.QPointF(
        widget_position.x(),
        widget_position.y())

    return PyQt6.QtGui.QMouseEvent(
        PyQt6.QtCore.QEvent.Type.MouseButtonPress,
        local_position,
        PyQt6.QtCore.Qt.MouseButton.LeftButton,
        PyQt6.QtCore.Qt.MouseButton.LeftButton,
        PyQt6.QtCore.Qt.KeyboardModifier.NoModifier)


def _build_mouse_move_event(
        widget_position: PyQt6.QtCore.QPoint) -> PyQt6.QtGui.QMouseEvent:
    """Build a mouse move event for direct handler invocation."""

    local_position = PyQt6.QtCore.QPointF(
        widget_position.x(),
        widget_position.y())

    return PyQt6.QtGui.QMouseEvent(
        PyQt6.QtCore.QEvent.Type.MouseMove,
        local_position,
        PyQt6.QtCore.Qt.MouseButton.NoButton,
        PyQt6.QtCore.Qt.MouseButton.NoButton,
        PyQt6.QtCore.Qt.KeyboardModifier.NoModifier)


def _build_key_press_event() -> PyQt6.QtGui.QKeyEvent:
    """Build a key press event for direct handler invocation."""

    return PyQt6.QtGui.QKeyEvent(
        PyQt6.QtCore.QEvent.Type.KeyPress,
        PyQt6.QtCore.Qt.Key.Key_A,
        PyQt6.QtCore.Qt.KeyboardModifier.NoModifier,
        "a")


def test_mouse_move_after_leave_restores_keyboard_forwarding(qt_application):
    """Mouse move repairs pointer-inside state cleared by a spurious leaveEvent."""

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_keyboard_tests(canvas)

    leave_event = PyQt6.QtCore.QEvent(PyQt6.QtCore.QEvent.Type.Leave)
    canvas.leaveEvent(leave_event)

    assert canvas._pointer_inside_canvas is False

    widget_position = PyQt6.QtCore.QPoint(100, 100)
    canvas.mouseMoveEvent(_build_mouse_move_event(widget_position))
    canvas.keyPressEvent(_build_key_press_event())

    messages = _drain_keyboard_messages(input_queue)

    assert canvas._pointer_inside_canvas is True
    assert len(messages) == 1
    assert isinstance(messages[0], aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_SCANCODE)
    assert messages[0].is_pressed is True


def test_mouse_press_focuses_canvas_for_keyboard(qt_application):
    """Canvas click calls setFocus so key events can reach the canvas."""

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_keyboard_tests(canvas)

    with unittest.mock.patch.object(
            canvas,
            "setFocus",
            wraps=canvas.setFocus) as set_focus_mock:

        canvas.mousePressEvent(_build_mouse_press_event(PyQt6.QtCore.QPoint(100, 100)))

    set_focus_mock.assert_called_once_with(PyQt6.QtCore.Qt.FocusReason.MouseFocusReason)


def test_refocus_keyboard_input_when_pointer_over_canvas(qt_application):
    """Refocus helper focuses the canvas when the pointer is over the session."""

    session_window = PyQt6.QtWidgets.QMainWindow()
    session_container = rdp_pipe.qt_session_window.RdpSessionContainer()
    session_window.setCentralWidget(session_container)
    canvas = session_container.canvas
    canvas.set_input_queue(queue.Queue())
    _configure_canvas_for_keyboard_tests(canvas)
    session_window.show()
    PyQt6.QtWidgets.QApplication.processEvents()

    pointer_over_canvas_position = PyQt6.QtCore.QPoint(100, 100)

    with unittest.mock.patch.object(
            canvas,
            "mapFromGlobal",
            return_value=pointer_over_canvas_position), \
            unittest.mock.patch.object(
                canvas,
                "setFocus",
                wraps=canvas.setFocus) as set_focus_mock:

        canvas.refocus_keyboard_input_if_pointer_over_canvas()

    set_focus_mock.assert_called_once_with(PyQt6.QtCore.Qt.FocusReason.MouseFocusReason)
    assert canvas._pointer_inside_canvas is True


def test_keyboard_debug_does_not_crash_on_key_press(qt_application, monkeypatch):
    """RDP_KEYBOARD_DEBUG logging does not crash keyPressEvent."""

    monkeypatch.setenv("RDP_KEYBOARD_DEBUG", "1")

    input_queue = queue.Queue()
    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_input_queue(input_queue)
    _configure_canvas_for_keyboard_tests(canvas)

    canvas.keyPressEvent(_build_key_press_event())

    messages = _drain_keyboard_messages(input_queue)

    assert len(messages) == 1
