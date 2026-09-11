"""Optional stderr tracing for remote pointer mirroring (RDP_POINTER_DEBUG=1)."""

import os
import sys


def is_pointer_debug_enabled() -> bool:
    """Return True when operator requested pointer tracing on stderr."""

    return os.environ.get("RDP_POINTER_DEBUG", "") == "1"


def write_pointer_debug(message: str):
    """Write one pointer-debug line to stderr when tracing is enabled."""

    if not is_pointer_debug_enabled():
        return

    sys.stderr.write(message)
    sys.stderr.write("\n")


def write_pointer_session_summary(
        pointer_cache,
        pointer_pdu_count_by_update_code: dict[int, int]):
    """Log pointer PDU counts and cache contents after connect."""

    if not is_pointer_debug_enabled():
        return

    sys.stderr.write(
        "pointer session summary: pdu_counts={pdu_counts}\n".format(
            pdu_counts=pointer_pdu_count_by_update_code))

    for cache_index in sorted(pointer_cache._entries_by_cache_index.keys()):
        pointer_update = pointer_cache._entries_by_cache_index[cache_index]
        image = pointer_update.image
        width = image.width if image is not None else 0
        height = image.height if image is not None else 0

        sys.stderr.write(
            "pointer cache[{cache_index}]: xor_bpp={xor_bpp} size={width}x{height}\n".format(
                cache_index=cache_index,
                xor_bpp=pointer_update.xor_bits_per_pixel,
                width=width,
                height=height))

    sys.stderr.write("\n")
