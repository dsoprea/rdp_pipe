"""Freedesktop entry used for Linux task switcher labels."""

import os

import rdp_pipe.config.entrypoint.rdp


def test_rdp_pipe_desktop_entry_name_matches_qt_display_name():
    """KDE reads Name= from the desktop file referenced by Qt desktopFileName."""

    repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    desktop_filepath = os.path.join(
        repository_root,
        "asset",
        "{desktop_basename}.desktop".format(
            desktop_basename=rdp_pipe.config.entrypoint.rdp.DESKTOP_ENTRY_BASENAME))

    with open(desktop_filepath, encoding="utf-8") as desktop_file:
        desktop_text = desktop_file.read()

    assert "Name={display_name}".format(
        display_name=rdp_pipe.config.entrypoint.rdp.QT_APPLICATION_DISPLAY_NAME) in desktop_text
