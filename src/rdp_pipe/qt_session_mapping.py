"""Widget-to-remote coordinate mapping for the Qt session canvas."""


def map_widget_position_to_remote(
        widget_width: int,
        widget_height: int,
        remote_width: int,
        remote_height: int,
        widget_x: int,
        widget_y: int) -> tuple[int, int] | None:
    """Map widget-local coordinates to remote desktop coordinates."""

    origin_x = int((widget_width - remote_width) / 2)
    origin_y = int((widget_height - remote_height) / 2)
    remote_x = widget_x - origin_x
    remote_y = widget_y - origin_y

    if remote_x < 0 or remote_y < 0:
        return None

    # Clamp bottom/right edge hovers so a 1px overshoot still hits the resize band.
    if remote_x >= remote_width:
        remote_x = remote_width - 1

    if remote_y >= remote_height:
        remote_y = remote_height - 1

    return remote_x, remote_y
