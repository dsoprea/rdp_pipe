"""Unit tests for Qt session canvas geometry vs framebuffer sizing."""

from unittest import mock

import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets
import pytest

import rdp_pipe.qt_session_window


@pytest.fixture(scope="module")
def qt_application():
    """Provide a single offscreen QApplication for Qt widget tests."""

    qt_application_instance = PyQt6.QtWidgets.QApplication.instance()

    if qt_application_instance is None:
        qt_application_instance = PyQt6.QtWidgets.QApplication([])

    return qt_application_instance


def _build_large_test_frame_image() -> PyQt6.QtGui.QImage:
    """Return a 1600x900 image matching a post-RDPDISP framebuffer."""

    frame_image = PyQt6.QtGui.QImage(
        1600,
        900,
        PyQt6.QtGui.QImage.Format.Format_RGB32)
    frame_image.fill(PyQt6.QtGui.QColor(32, 32, 32).rgb())

    return frame_image


def test_canvas_stays_shrinkable_after_large_frame_image(qt_application):
    """RdpCanvas stays shrinkable after a large framebuffer without QLabel pixmap hints."""

    canvas = rdp_pipe.qt_session_window.RdpCanvas()
    canvas.set_frame_image(_build_large_test_frame_image())

    assert canvas.minimumSize().width() == 0
    assert canvas.minimumSize().height() == 0

    parent_widget = PyQt6.QtWidgets.QWidget()
    parent_widget.resize(1400, 800)
    canvas.setParent(parent_widget)
    canvas.setGeometry(0, 0, 1400, 800)

    assert canvas.width() == 1400
    assert canvas.height() == 800


def test_main_window_stays_shrinkable_after_large_frame_image(qt_application):
    """A main-window shell does not inherit a large minimum size from the framebuffer."""

    main_window = PyQt6.QtWidgets.QMainWindow()
    main_window.setMinimumSize(0, 0)
    session_container = rdp_pipe.qt_session_window.RdpSessionContainer()
    main_window.setCentralWidget(session_container)
    session_container.canvas.set_frame_image(_build_large_test_frame_image())
    main_window.resize(1500, 900)
    main_window.resize(1400, 800)

    assert main_window.width() == 1400
    assert main_window.height() == 800


def test_session_container_resize_debounce_emits_client_area_size(qt_application):
    """Container resize debounce uses the container rect, not framebuffer size hints."""

    container = rdp_pipe.qt_session_window.RdpSessionContainer()
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


def _build_session_window_with_mock_worker(
        autoresize_enabled: bool) -> tuple[
            rdp_pipe.qt_session_window.RdpSessionWindow,
            mock.Mock]:

    mock_worker = mock.Mock()
    mock_session = mock.Mock()
    mock_session.display_caps_unavailable = False
    mock_worker.get_session.return_value = mock_session
    mock_worker_thread = mock.Mock()

    with mock.patch(
            "rdp_pipe.rdp_session_thread.RdpSessionWorker",
            return_value=mock_worker):
        with mock.patch(
                "PyQt6.QtCore.QThread",
                return_value=mock_worker_thread):
            session_window = rdp_pipe.qt_session_window.RdpSessionWindow(
                "rdp+ntlm-password://user@10.0.0.5",
                1280,
                800,
                autoresize_enabled=autoresize_enabled)

    return session_window, mock_worker


def test_no_autoresize_skips_remote_resolution_request(qt_application):
    """--no-autoresize must not send RDPDISP layout requests on window resize."""

    session_window, mock_worker = _build_session_window_with_mock_worker(False)
    session_window._session_rdp_ready = True
    session_window._handle_canvas_resize_requested(1600, 900)

    mock_worker.request_remote_resolution.assert_not_called()


def test_autoresize_forwards_remote_resolution_request(qt_application):
    """Default autoresize sends RDPDISP layout requests after session ready."""

    session_window, mock_worker = _build_session_window_with_mock_worker(True)
    session_window._session_rdp_ready = True
    session_window._handle_canvas_resize_requested(1601, 901)

    mock_worker.request_remote_resolution.assert_called_once_with(1600, 901)
