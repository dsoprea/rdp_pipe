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


def test_linux_session_window_uses_frameless_menu_widget_title_bar(
        qt_application,
        monkeypatch):
    """Linux places special-key buttons in the frameless menu-widget title bar."""

    monkeypatch.setattr(sys, "platform", "linux")

    session_window = rdp_pipe.qt_session_window.RdpSessionWindow.__new__(
        rdp_pipe.qt_session_window.RdpSessionWindow)
    PyQt6.QtWidgets.QMainWindow.__init__(session_window)
    session_window._session_title_bar = None
    session_window.setWindowTitle("RDP - test")
    session_window._configure_session_window_title_bar_chrome()

    assert session_window._session_title_bar is not None
    assert isinstance(
        session_window.menuWidget(),
        rdp_pipe.qt_session_window.RdpSessionTitleBar)
    assert bool(
        session_window.windowFlags()
        & PyQt6.QtCore.Qt.WindowType.FramelessWindowHint)
