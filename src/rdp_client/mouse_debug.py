"""Optional stderr tracing for mouse input forwarding (RDP_MOUSE_DEBUG=1)."""

import os
import sys


def is_mouse_debug_enabled() -> bool:
    """Return True when operator requested mouse input tracing on stderr."""

    return os.environ.get("RDP_MOUSE_DEBUG", "") == "1"


def write_mouse_debug(message: str):
    """Write one mouse-debug line to stderr when tracing is enabled."""

    if not is_mouse_debug_enabled():
        return

    sys.stderr.write(message)
    sys.stderr.write("\n")
