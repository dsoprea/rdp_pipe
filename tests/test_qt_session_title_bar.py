"""Unit tests for session window title bar chrome."""

import sys

import PyQt6.QtCore
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


def _build_linux_frameless_session_window_with_title_bar(monkeypatch):
    """Return a frameless RdpSessionWindow with title bar wired like production Linux."""

    monkeypatch.setattr(sys, "platform", "linux")

    session_window = rdp_pipe.qt_session_window.RdpSessionWindow.__new__(
        rdp_pipe.qt_session_window.RdpSessionWindow)
    PyQt6.QtWidgets.QMainWindow.__init__(session_window)
    session_window._session_title_bar = None
    session_window._frameless_resize_grip_entries = []
    session_window._session_container = rdp_pipe.qt_session_window.RdpSessionContainer()
    session_window.setWindowTitle("RDP - test")
    session_window._configure_session_window_title_bar_chrome()

    return session_window


def test_linux_session_window_uses_frameless_title_bar_in_central_layout(
        qt_application,
        monkeypatch):
    """Linux stacks the custom title bar above the session canvas inside the client area."""

    session_window = _build_linux_frameless_session_window_with_title_bar(monkeypatch)
    session_window.setCentralWidget(session_window._build_session_central_widget())

    assert session_window._session_title_bar is not None
    central_layout = session_window.centralWidget().layout()
    assert central_layout is not None
    assert central_layout.itemAt(0).widget() is session_window._session_title_bar
    assert isinstance(
        session_window._session_title_bar,
        rdp_pipe.qt_session_window.RdpSessionTitleBar)
    assert bool(
        session_window.windowFlags()
        & PyQt6.QtCore.Qt.WindowType.FramelessWindowHint)
    assert len(session_window._frameless_resize_grip_entries) == len(
        rdp_pipe.qt_session_window.FRAMELESS_RESIZE_GRIP_EDGES)


def test_session_title_bar_maximize_button_has_icon_after_construction(
        qt_application,
        monkeypatch):
    """Maximize control must ship a non-null icon (theme or Qt style fallback)."""

    session_window = _build_linux_frameless_session_window_with_title_bar(monkeypatch)
    session_title_bar = session_window._session_title_bar
    maximize_icon = session_title_bar._maximize_button.icon()

    assert maximize_icon.isNull() is False


def test_session_title_bar_controls_exclude_keyboard_focus(qt_application, monkeypatch):
    """Title-bar chrome must not participate in Qt Tab focus navigation."""

    session_window = _build_linux_frameless_session_window_with_title_bar(monkeypatch)
    session_title_bar = session_window._session_title_bar
    no_focus_policy = PyQt6.QtCore.Qt.FocusPolicy.NoFocus

    assert session_title_bar.focusPolicy() == no_focus_policy
    assert session_title_bar._title_label.focusPolicy() == no_focus_policy
    assert session_title_bar._ctrl_alt_del_button.focusPolicy() == no_focus_policy
    assert session_title_bar._super_button.focusPolicy() == no_focus_policy
    assert session_title_bar._minimize_button.focusPolicy() == no_focus_policy
    assert session_title_bar._maximize_button.focusPolicy() == no_focus_policy
    assert session_title_bar._close_button.focusPolicy() == no_focus_policy


def test_session_title_bar_maximize_icon_changes_when_window_maximized(
        qt_application,
        monkeypatch):
    """Maximize vs restore icons must differ when the session window is maximized."""

    session_window = _build_linux_frameless_session_window_with_title_bar(monkeypatch)
    session_title_bar = session_window._session_title_bar
    session_window.show()
    qt_application.processEvents()
    maximize_cache_key = session_title_bar._maximize_button.icon().cacheKey()
    session_window.showMaximized()
    qt_application.processEvents()
    session_title_bar.sync_maximize_button_icon()
    restored_cache_key = session_title_bar._maximize_button.icon().cacheKey()

    assert restored_cache_key != maximize_cache_key


def test_compute_frameless_resize_grip_geometry_for_bottom_edge(qt_application):
    """Bottom edge grip sits above the window bottom with side insets for corners."""

    margin_pixels = rdp_pipe.qt_session_window.FRAMELESS_RESIZE_MARGIN_PIXELS
    grip_geometry = \
        rdp_pipe.qt_session_window.compute_frameless_resize_grip_geometry(
            PyQt6.QtCore.Qt.Edge.BottomEdge,
            800,
            600,
            margin_pixels)

    assert grip_geometry.top() == 600 - margin_pixels
    assert grip_geometry.height() == margin_pixels
    assert grip_geometry.left() == margin_pixels
    assert grip_geometry.width() == 800 - (2 * margin_pixels)


def test_outer_window_height_includes_frameless_title_bar(qt_application):
    """Default 800px canvas height must add title bar pixels to the outer window."""

    outer_height = \
        rdp_pipe.qt_session_window.compute_session_window_outer_height_for_client_area(
            800,
            True)

    assert outer_height == 800 + rdp_pipe.qt_session_window.SESSION_TITLE_BAR_HEIGHT


def test_compute_frameless_resized_frame_geometry_grows_bottom_right(qt_application):
    """Dragging the bottom-right grip increases width and height."""

    start_geometry = PyQt6.QtCore.QRect(100, 100, 400, 300)
    global_delta = PyQt6.QtCore.QPoint(20, 15)
    resize_edge = (
        PyQt6.QtCore.Qt.Edge.BottomEdge | PyQt6.QtCore.Qt.Edge.RightEdge)
    resized_geometry = \
        rdp_pipe.qt_session_window.compute_frameless_resized_frame_geometry(
            start_geometry,
            resize_edge,
            global_delta,
            320,
            240)

    assert resized_geometry.width() == 420
    assert resized_geometry.height() == 315


def test_resolve_frameless_resize_edge_returns_none_in_center(qt_application):
    """Center clicks are not edge resize grips."""

    probe_window = PyQt6.QtWidgets.QWidget()
    probe_window.resize(800, 600)

    resize_edge = rdp_pipe.qt_session_window.resolve_frameless_resize_edge(
        probe_window,
        PyQt6.QtCore.QPoint(400, 300))

    assert resize_edge is None


def test_resolve_frameless_resize_edge_detects_bottom_right_corner(qt_application):
    """Bottom-right corner presses combine bottom and right edges."""

    probe_window = PyQt6.QtWidgets.QWidget()
    probe_window.resize(800, 600)

    resize_edge = rdp_pipe.qt_session_window.resolve_frameless_resize_edge(
        probe_window,
        PyQt6.QtCore.QPoint(799, 599))

    assert resize_edge == (
        PyQt6.QtCore.Qt.Edge.BottomEdge | PyQt6.QtCore.Qt.Edge.RightEdge)
