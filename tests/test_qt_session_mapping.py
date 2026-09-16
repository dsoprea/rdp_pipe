"""Unit tests for widget-to-remote coordinate mapping used by the Qt canvas."""

import rdp_pipe.qt_session_mapping


def test_map_widget_position_uses_negative_letterbox_origin_when_clipped():
    """A horizontally clipped framebuffer maps widget (0, 0) to remote (128, 0)."""

    mapped_position = rdp_pipe.qt_session_mapping.map_widget_position_to_remote(
        1024,
        800,
        1280,
        800,
        0,
        0)

    assert mapped_position == (128, 0)


def test_map_widget_position_clamps_bottom_right_edge_to_last_pixel():
    """A hover one pixel past the framebuffer maps to the bottom-right resize band."""

    mapped_position = rdp_pipe.qt_session_mapping.map_widget_position_to_remote(
        1280,
        800,
        1280,
        800,
        1280,
        800)

    assert mapped_position == (1279, 799)


def test_map_widget_position_rejects_letterbox_margins():
    """Hover in black bars must not map to remote (0, 0)."""

    mapped_position = rdp_pipe.qt_session_mapping.map_widget_position_to_remote(
        1920,
        1080,
        1280,
        800,
        100,
        100)

    assert mapped_position is None


def test_map_widget_position_uses_session_dimensions_not_pixmap_size():
    """Letterbox math follows authoritative remote session size ahead of the pixmap."""

    mapped_position = rdp_pipe.qt_session_mapping.map_widget_position_to_remote(
        1920,
        1080,
        1600,
        900,
        960,
        540)

    assert mapped_position == (800, 450)
