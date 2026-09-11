"""Unit tests for widget-to-remote coordinate mapping used by the Qt canvas."""


def _map_widget_position_to_remote(
        widget_width: int,
        widget_height: int,
        remote_width: int,
        remote_height: int,
        widget_x: int,
        widget_y: int) -> tuple[int, int] | None:

    origin_x = int((widget_width - remote_width) / 2)
    origin_y = int((widget_height - remote_height) / 2)
    remote_x = widget_x - origin_x
    remote_y = widget_y - origin_y

    if remote_x < 0 or remote_y < 0:
        return None

    if remote_x >= remote_width:
        remote_x = remote_width - 1

    if remote_y >= remote_height:
        remote_y = remote_height - 1

    return remote_x, remote_y


def test_map_widget_position_uses_negative_letterbox_origin_when_clipped():
    """A horizontally clipped framebuffer maps widget (0, 0) to remote (128, 0)."""

    mapped_position = _map_widget_position_to_remote(
        1024,
        800,
        1280,
        800,
        0,
        0)

    assert mapped_position == (128, 0)


def test_map_widget_position_clamps_bottom_right_edge_to_last_pixel():
    """A hover one pixel past the framebuffer maps to the bottom-right resize band."""

    mapped_position = _map_widget_position_to_remote(
        1280,
        800,
        1280,
        800,
        1280,
        800)

    assert mapped_position == (1279, 799)


def test_map_widget_position_rejects_letterbox_margins():
    """Hover in black bars must not map to remote (0, 0)."""

    mapped_position = _map_widget_position_to_remote(
        1920,
        1080,
        1280,
        800,
        100,
        100)

    assert mapped_position is None
