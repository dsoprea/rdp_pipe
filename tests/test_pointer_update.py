"""Unit tests for RDP pointer mask decoding and cache behavior."""

import asyncio
import unittest.mock

import aardwolf.protocol.fastpath
import aardwolf.protocol.fastpath.pointer

import rdp_pipe.pointer_update
import rdp_pipe.rdp_connection


def test_build_rgba_image_from_monochrome_masks_opaque_black_pixel():
    """A 1x1 monochrome pointer with AND=0 and XOR=0 decodes to opaque black."""

    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        1,
        1,
        1,
        b"\x00",
        b"\x00")

    assert rgba_image.size == (1, 1)
    assert rgba_image.getpixel((0, 0)) == (0, 0, 0, 255)


def test_build_rgba_image_from_monochrome_masks_transparent_pixel():
    """A 1x1 monochrome pointer with AND=1 and XOR=0 decodes to transparent."""

    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        1,
        1,
        1,
        b"\x00",
        b"\x80")

    assert rgba_image.getpixel((0, 0)) == (0, 0, 0, 0)


def test_fixup_24bpp_rgba_image_from_missing_and_mask_makes_black_matte_transparent():
    """24-bpp cursors with a missing AND mask should not paint a solid black box."""

    # Bottom-up 24-bpp: bottom row black, top row black + white at (1, 0).
    xor_mask_data = bytes([
        0, 0, 0, 0, 0, 0,
        0, 0, 0, 255, 255, 255,
    ])
    and_mask_data = bytes([
        0x00, 0x00,
        0x00, 0x00,
    ])

    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        2,
        2,
        24,
        xor_mask_data,
        and_mask_data)

    assert rdp_pipe.pointer_update.count_pointer_image_visible_pixels(rgba_image) == 4

    fixed_rgba_image = \
        rdp_pipe.pointer_update.fixup_24bpp_rgba_image_from_missing_and_mask(rgba_image)

    assert rdp_pipe.pointer_update.count_pointer_image_visible_pixels(fixed_rgba_image) == 1
    assert fixed_rgba_image.getpixel((1, 0)) == (255, 255, 255, 255)


def test_build_rgba_image_from_32bpp_masks_respects_alpha_channel():
    """32-bpp pointers keep per-pixel alpha when the AND mask bit is clear."""

    xor_mask_data = bytes([
        0, 0, 0, 0,
        0, 0, 0, 0,
        255, 255, 255, 255,
        0, 0, 0, 0,
    ])
    and_mask_data = bytes([
        0x00, 0x00,
        0x00, 0x00,
    ])

    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        2,
        2,
        32,
        xor_mask_data,
        and_mask_data)

    assert rdp_pipe.pointer_update.count_pointer_image_visible_pixels(rgba_image) == 1
    assert rgba_image.getpixel((0, 0)) == (255, 255, 255, 255)
    assert rgba_image.getpixel((1, 0)) == (0, 0, 0, 0)


def test_build_rgba_image_from_monochrome_masks_uses_top_down_scanlines():
    """1-bpp monochrome pointers are read top-down (color pointers are bottom-up)."""

    xor_mask_data = bytes([
        0b00000000,
        0b00000000,
        0b10000000,
        0b00000000,
    ])
    and_mask_data = bytes([
        0x00, 0x00,
        0x00, 0x00,
    ])

    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        2,
        2,
        1,
        xor_mask_data,
        and_mask_data)

    assert rgba_image.getpixel((0, 0)) == (0, 0, 0, 255)
    assert rgba_image.getpixel((0, 1)) == (255, 255, 255, 255)


def test_build_rgba_image_from_color_masks_uses_bottom_up_xor_scanlines():
    """24-bpp color pointers are read bottom-up with padded scanlines."""

    # 2x2 pointer stored bottom-up: bottom row blue, top row red (BGR order).
    xor_mask_data = bytes([
        255, 0, 0, 255, 0, 0,
        0, 0, 255, 0, 0, 255,
    ])
    and_mask_data = bytes([
        0x00, 0x00,
        0x00, 0x00,
    ])

    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        2,
        2,
        24,
        xor_mask_data,
        and_mask_data)

    assert rgba_image.size == (2, 2)
    assert rgba_image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert rgba_image.getpixel((1, 0)) == (255, 0, 0, 255)
    assert rgba_image.getpixel((0, 1)) == (0, 0, 255, 255)
    assert rgba_image.getpixel((1, 1)) == (0, 0, 255, 255)


def test_pointer_cache_stores_and_resolves_cached_index():
    """CACHED pointer updates resolve through the pointer cache."""

    pointer_cache = rdp_pipe.pointer_update.RdpPointerCache()
    rgba_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        1,
        1,
        1,
        b"\x00",
        b"\x00")

    stored_update = rdp_pipe.pointer_update.RdpPointerUpdate.build_bitmap(
        0,
        0,
        rgba_image)

    pointer_cache.store_bitmap(7, stored_update)

    cached_update = pointer_cache.lookup_bitmap(7)

    assert cached_update is stored_update
    assert pointer_cache.lookup_bitmap(99) is None


def test_get_last_stored_bitmap_update_returns_highest_cache_index():
    """Hydration after connect uses the most recently stored cache entry."""

    pointer_cache = rdp_pipe.pointer_update.RdpPointerCache()
    first_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        1,
        1,
        1,
        b"\x00",
        b"\x00")
    second_image = rdp_pipe.pointer_update.build_rgba_image_from_pointer_masks(
        1,
        1,
        1,
        b"\xFF",
        b"\x00")

    first_update = rdp_pipe.pointer_update.RdpPointerUpdate.build_bitmap(
        0,
        0,
        first_image,
        cache_index=1)
    second_update = rdp_pipe.pointer_update.RdpPointerUpdate.build_bitmap(
        0,
        0,
        second_image,
        cache_index=3)

    pointer_cache.store_bitmap(1, first_update)
    pointer_cache.store_bitmap(3, second_update)

    assert pointer_cache.get_last_stored_bitmap_update() is second_update
    assert pointer_cache.get_last_stored_bitmap_update() is not None


def test_extract_pointer_mask_bytes_corrects_aardwolf_swapped_masks():
    """aardwolf reads xor/and lengths onto the wrong mask buffers."""

    width = 32
    height = 32
    xor_bits_per_pixel = 32
    expected_xor_byte_count = \
        rdp_pipe.pointer_update.compute_expected_xor_mask_byte_count(
            width,
            height,
            xor_bits_per_pixel)
    expected_and_byte_count = \
        rdp_pipe.pointer_update.compute_expected_and_mask_byte_count(width, height)

    xor_mask_data = bytes([index % 256 for index in range(expected_xor_byte_count)])
    and_mask_data = bytes([0xFF] * expected_and_byte_count)

    corrected_xor, corrected_and = rdp_pipe.pointer_update.extract_pointer_mask_bytes(
        width,
        height,
        xor_bits_per_pixel,
        and_mask_data,
        xor_mask_data,
        expected_xor_byte_count,
        expected_and_byte_count)

    assert corrected_xor == xor_mask_data
    assert corrected_and == and_mask_data


def test_monochrome_beam_pointer_with_all_and_bits_set_uses_invert_mask():
    """I-beam/resize cursors with every AND bit set decode to framebuffer-invert pixels."""

    # Top-down 2x2 XOR pattern with every AND bit set.
    xor_mask_data = bytes([
        0b00000000,
        0b00000000,
        0b11000000,
        0b00000000,
    ])
    and_mask_data = bytes([
        0xFF,
        0xFF,
        0xFF,
        0xFF,
    ])

    rgba_image, invert_mask_image = \
        rdp_pipe.pointer_update.build_pointer_images_from_pointer_masks(
            2,
            2,
            1,
            xor_mask_data,
            and_mask_data)

    assert rgba_image.getpixel((0, 1)) == (0, 0, 0, 0)
    assert invert_mask_image.getpixel((0, 1)) == 255
    assert invert_mask_image.getpixel((1, 1)) == 255
    assert rdp_pipe.pointer_update.pointer_image_has_visible_pixels(
        rgba_image,
        invert_mask_image)


def test_build_pointer_images_marks_monochrome_invert_pixels():
    """1x1 AND=1 XOR=1 decodes to transparent RGBA with the invert mask set."""

    rgba_image, invert_mask_image = \
        rdp_pipe.pointer_update.build_pointer_images_from_pointer_masks(
            1,
            1,
            1,
            b"\x80",
            b"\x80")

    assert rgba_image.getpixel((0, 0)) == (0, 0, 0, 0)
    assert invert_mask_image.getpixel((0, 0)) == 255


def test_build_composited_pointer_inverts_white_background_to_black():
    """Framebuffer inversion over white yields black cursor pixels."""

    rgba_image, invert_mask_image = \
        rdp_pipe.pointer_update.build_pointer_images_from_pointer_masks(
            1,
            1,
            1,
            b"\x80",
            b"\x80")

    def sample_white_background(widget_x: int, widget_y: int):
        return 255, 255, 255

    composited_image = rdp_pipe.pointer_update.build_composited_pointer_rgba_image(
        rgba_image,
        invert_mask_image,
        0,
        0,
        sample_white_background)

    assert composited_image.getpixel((0, 0)) == (0, 0, 0, 255)


def test_build_composited_pointer_inverts_black_background_to_white():
    """Framebuffer inversion over black yields white cursor pixels."""

    rgba_image, invert_mask_image = \
        rdp_pipe.pointer_update.build_pointer_images_from_pointer_masks(
            1,
            1,
            1,
            b"\x80",
            b"\x80")

    def sample_black_background(widget_x: int, widget_y: int):
        return 0, 0, 0

    composited_image = rdp_pipe.pointer_update.build_composited_pointer_rgba_image(
        rgba_image,
        invert_mask_image,
        0,
        0,
        sample_black_background)

    assert composited_image.getpixel((0, 0)) == (255, 255, 255, 255)


def test_parse_color_pointer_update_data_reads_xor_before_and():
    """Wire parsing uses xor length before and length."""

    color_update_data = (
        b"\x03\x00"
        b"\x01\x00\x02\x00"
        b"\x02\x00\x02\x00"
        b"\x04\x00"
        b"\x0c\x00"
        b"\xff\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
    )

    cache_index, hotspot_x, hotspot_y, width, height, xor_mask_data, and_mask_data = \
        rdp_pipe.pointer_update.parse_color_pointer_update_data(color_update_data)

    assert cache_index == 3
    assert hotspot_x == 1
    assert hotspot_y == 2
    assert width == 2
    assert height == 2
    assert xor_mask_data == b"\xff\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00"
    assert and_mask_data == b"\x00\x00\x00\x00"


def test_process_pointer_fastpath_update_default_restores_system_cursor():
    """PTR_DEFAULT clears a previously applied bitmap cursor such as the busy spinner."""

    connection = unittest.mock.Mock()
    connection._pointer_cache = rdp_pipe.pointer_update.RdpPointerCache()
    fastpath_update = unittest.mock.Mock()
    fastpath_update.updateCode = aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.PTR_DEFAULT

    pointer_update = asyncio.run(
        rdp_pipe.rdp_connection._process_pointer_fastpath_update(
            connection,
            fastpath_update))

    assert pointer_update.kind == rdp_pipe.pointer_update.RdpPointerUpdateKind.DEFAULT


def test_process_pointer_fastpath_update_null_hides_pointer():
    """PTR_NULL maps to a hidden-pointer update for the GUI layer."""

    connection = unittest.mock.Mock()
    connection._pointer_cache = rdp_pipe.pointer_update.RdpPointerCache()
    fastpath_update = unittest.mock.Mock()
    fastpath_update.updateCode = aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.PTR_NULL

    pointer_update = asyncio.run(
        rdp_pipe.rdp_connection._process_pointer_fastpath_update(
            connection,
            fastpath_update))

    assert pointer_update.kind == rdp_pipe.pointer_update.RdpPointerUpdateKind.HIDDEN


def test_build_bitmap_pointer_update_from_color_attribute_round_trip():
    """TS_FP_COLORPOINTERATTRIBUTE decodes to a bitmap pointer update with hotspot."""

    color_pointer_attribute = aardwolf.protocol.fastpath.pointer.TS_FP_COLORPOINTERATTRIBUTE()
    color_pointer_attribute.cacheIndex = 3
    color_pointer_attribute.hotSpot = aardwolf.protocol.fastpath.pointer.TS_POINT16()
    color_pointer_attribute.hotSpot.xPos = 1
    color_pointer_attribute.hotSpot.yPos = 2
    color_pointer_attribute.width = 1
    color_pointer_attribute.height = 1
    color_pointer_attribute.lengthAndMask = 2
    color_pointer_attribute.lengthXorMask = 4
    color_pointer_attribute.xorMaskData = b"\x00\x00\x00\x00"
    color_pointer_attribute.andMaskData = b"\x00\x00"

    pointer_cache = rdp_pipe.pointer_update.RdpPointerCache()
    pointer_update = \
        rdp_pipe.pointer_update.build_bitmap_pointer_update_from_color_attribute(
            color_pointer_attribute,
            24,
            pointer_cache)

    assert pointer_update.kind == rdp_pipe.pointer_update.RdpPointerUpdateKind.BITMAP
    assert pointer_update.hotspot_x == 0
    assert pointer_update.hotspot_y == 0
    assert pointer_update.image.size == (1, 1)
    assert pointer_cache.lookup_bitmap(3) is pointer_update
