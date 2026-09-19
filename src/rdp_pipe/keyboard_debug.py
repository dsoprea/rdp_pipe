"""Optional stderr tracing for keyboard input forwarding (RDP_KEYBOARD_DEBUG=1)."""

import os
import sys


def is_keyboard_debug_enabled() -> bool:
    """Return True when operator requested keyboard input tracing on stderr."""

    return os.environ.get("RDP_KEYBOARD_DEBUG", "") == "1"


def write_keyboard_debug(message: str):
    """Write one keyboard-debug line to stderr when tracing is enabled."""

    if not is_keyboard_debug_enabled():
        return

    sys.stderr.write(message)
    sys.stderr.write("\n")
