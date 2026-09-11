"""Unit tests for Qt session canvas geometry vs pixmap sizing."""

import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets
import pytest

import rdp_client.qt_session_window


@pytest.fixture(scope="module")
def qt_application():
    """Provide a single offscreen QApplication for Qt widget tests."""

    qt_application_instance = PyQt6.QtWidgets.QApplication.instance()

    if qt_application_instance is None:
        qt_application_instance = PyQt6.QtWidgets.QApplication([])

    return qt_application_instance


def _build_large_test_pixmap() -> PyQt6.QtGui.QPixmap:
    """Return a 1600x900 pixmap matching a post-RDPDISP framebuffer."""

    pixmap = PyQt6.QtGui.QPixmap(1600, 900)
    pixmap.fill(PyQt6.QtGui.QColor(32, 32, 32))

    return pixmap


def test_canvas_minimum_size_hint_does_not_block_shrink_after_set_pixmap(qt_application):
    """RdpCanvas stays shrinkable after setPixmap when minimum size is cleared."""

    canvas = rdp_client.qt_session_window.RdpCanvas()
    canvas.setPixmap(_build_large_test_pixmap())

    assert canvas.minimumSize().width() == 0
    assert canvas.minimumSize().height() == 0

    parent_widget = PyQt6.QtWidgets.QWidget()
    parent_widget.resize(1400, 800)
    canvas.setParent(parent_widget)
    canvas.setGeometry(0, 0, 1400, 800)

    assert canvas.width() == 1400
    assert canvas.height() == 800


def test_session_container_resize_debounce_emits_client_area_size(qt_application):
    """Container resize debounce uses the container rect, not pixmap size hints."""

    container = rdp_client.qt_session_window.RdpSessionContainer()
    container.resize(1500, 850)
    container.resizeEvent(
        PyQt6.QtGui.QResizeEvent(
            PyQt6.QtCore.QSize(1500, 850),
            PyQt6.QtCore.QSize(1280, 800)))

    emitted_sizes: list[tuple[int, int]] = []

    def capture_resize_requested(width: int, height: int):
        emitted_sizes.append((width, height))

    container.resize_requested.connect(capture_resize_requested)
    container._emit_debounced_resize()

    assert emitted_sizes == [(1500, 850)]
