"""RDP server pointer updates decoded for local Qt cursor mirroring."""

import enum
import io

import PIL.Image


class RdpPointerUpdateKind(enum.Enum):
    """Kind of pointer update emitted to the GUI layer."""

    DEFAULT = "default"
    HIDDEN = "hidden"
    BITMAP = "bitmap"


class RdpPointerUpdate:
    """Server pointer shape update bridged from fast-path PDUs to Qt."""

    def __init__(
            self,
            kind: RdpPointerUpdateKind,
            hotspot_x: int = 0,
            hotspot_y: int = 0,
            image: PIL.Image.Image | None = None,
            cache_index: int | None = None,
            xor_bits_per_pixel: int | None = None,
            invert_mask_image: PIL.Image.Image | None = None):

        """Store pointer kind, hotspot, RGBA bitmap, and optional invert mask."""

        self.kind = kind
        self.hotspot_x = hotspot_x
        self.hotspot_y = hotspot_y
        self.image = image
        self.cache_index = cache_index
        self.xor_bits_per_pixel = xor_bits_per_pixel
        self.invert_mask_image = invert_mask_image

    @staticmethod
    def build_default() -> RdpPointerUpdate:
        """Return an update that restores the system default arrow."""

        return RdpPointerUpdate(RdpPointerUpdateKind.DEFAULT)

    @staticmethod
    def build_hidden() -> RdpPointerUpdate:
        """Return an update that hides the pointer."""

        return RdpPointerUpdate(RdpPointerUpdateKind.HIDDEN)

    @staticmethod
    def build_bitmap(
            hotspot_x: int,
            hotspot_y: int,
            image: PIL.Image.Image,
            cache_index: int | None = None,
            xor_bits_per_pixel: int | None = None,
            invert_mask_image: PIL.Image.Image | None = None) -> RdpPointerUpdate:

        """Return an update that sets a custom bitmap cursor."""

        return RdpPointerUpdate(
            RdpPointerUpdateKind.BITMAP,
            hotspot_x=hotspot_x,
            hotspot_y=hotspot_y,
            image=image,
            cache_index=cache_index,
            xor_bits_per_pixel=xor_bits_per_pixel,
            invert_mask_image=invert_mask_image)


class RdpPointerCache:
    """Cache of server pointer bitmaps keyed by RDP cache index."""

    def __init__(self):
        """Initialize an empty pointer cache."""

        self._entries_by_cache_index: dict[int, RdpPointerUpdate] = {}

    def store_bitmap(self, cache_index: int, pointer_update: RdpPointerUpdate):
        """Store a bitmap pointer update for later CACHED lookups."""

        self._entries_by_cache_index[cache_index] = pointer_update

    def lookup_bitmap(self, cache_index: int) -> RdpPointerUpdate | None:
        """Return a cached bitmap update or None when the index is unknown."""

        try:
            return self._entries_by_cache_index[cache_index]

        except KeyError:
            return None

    def get_last_stored_bitmap_update(self) -> RdpPointerUpdate | None:
        """Return the bitmap stored at the highest cache index, if any."""

        if not self._entries_by_cache_index:
            return None

        last_cache_index = max(self._entries_by_cache_index.keys())

        return self._entries_by_cache_index[last_cache_index]


def compute_and_scanline_byte_count(width: int) -> int:
    """Return padded 1-bpp AND mask bytes per scanline."""

    scanline_byte_count = (width + 7) // 8
    if scanline_byte_count % 2 != 0:
        scanline_byte_count = scanline_byte_count + 1

    return scanline_byte_count


def compute_expected_xor_mask_byte_count(
        width: int,
        height: int,
        xor_bits_per_pixel: int) -> int:

    """Return total XOR mask bytes for a pointer of the given geometry."""

    xor_scanline_byte_count = compute_xor_scanline_byte_count(width, xor_bits_per_pixel)

    return xor_scanline_byte_count * height


def compute_expected_and_mask_byte_count(width: int, height: int) -> int:
    """Return total AND mask bytes for a pointer of the given geometry."""

    and_scanline_byte_count = compute_and_scanline_byte_count(width)

    return and_scanline_byte_count * height


def parse_color_pointer_update_data(
        color_update_data: bytes,
        xor_bits_per_pixel: int | None = None) -> tuple[int, int, int, int, int, bytes, bytes]:

    """Parse TS_FP_COLORPOINTERATTRIBUTE bytes with correct xor/and mask order."""

    buffer = io.BytesIO(color_update_data)
    cache_index = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    hotspot_x = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    hotspot_y = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    width = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    height = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    length_and_mask = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    length_xor_mask = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
    mask_payload = buffer.read()

    if xor_bits_per_pixel is not None and width > 0 and height > 0:
        expected_xor_byte_count = \
            compute_expected_xor_mask_byte_count(width, height, xor_bits_per_pixel)
        expected_and_byte_count = compute_expected_and_mask_byte_count(width, height)

        if len(mask_payload) >= expected_xor_byte_count + expected_and_byte_count:
            xor_mask_data = mask_payload[:expected_xor_byte_count]
            and_mask_data = mask_payload[
                expected_xor_byte_count:expected_xor_byte_count + expected_and_byte_count]

            return (
                cache_index,
                hotspot_x,
                hotspot_y,
                width,
                height,
                xor_mask_data,
                and_mask_data)

    xor_mask_data = mask_payload[:length_xor_mask]
    and_mask_data = mask_payload[length_xor_mask:length_xor_mask + length_and_mask]

    return (
        cache_index,
        hotspot_x,
        hotspot_y,
        width,
        height,
        xor_mask_data,
        and_mask_data)


def are_all_and_mask_bytes_zero(and_mask_data: bytes, width: int, height: int) -> bool:
    """Return True when every AND mask byte in the pointer geometry is 0x00."""

    expected_and_byte_count = compute_expected_and_mask_byte_count(width, height)

    if len(and_mask_data) < expected_and_byte_count:
        return True

    for byte_index in range(expected_and_byte_count):
        if and_mask_data[byte_index] != 0x00:
            return False

    return True


def are_all_and_mask_bytes_set_to_opaque(and_mask_data: bytes, width: int, height: int) -> bool:
    """Return True when every AND mask byte is 0xFF (beam/resize cursor encoding)."""

    expected_and_byte_count = compute_expected_and_mask_byte_count(width, height)

    if len(and_mask_data) < expected_and_byte_count:
        return False

    for byte_index in range(expected_and_byte_count):
        if and_mask_data[byte_index] != 0xFF:
            return False

    return True


def fixup_monochrome_beam_pointer_masks(
        width: int,
        height: int,
        xor_mask_data: bytes,
        and_mask_data: bytes) -> tuple[bytes, bytes]:

    """Repair I-beam/resize monochrome pointers that set every AND bit to 1."""

    if not are_all_and_mask_bytes_set_to_opaque(and_mask_data, width, height):
        return xor_mask_data, and_mask_data

    xor_scanline_byte_count = compute_xor_scanline_byte_count(width, 1)
    mask_byte_count = xor_scanline_byte_count * height
    fixed_xor_mask_data = bytes(mask_byte_count)
    fixed_and_mask_data = bytes(
        (~xor_mask_data[byte_index]) & 0xFF for byte_index in range(mask_byte_count))

    return fixed_xor_mask_data, fixed_and_mask_data


def extract_pointer_mask_bytes(
        width: int,
        height: int,
        xor_bits_per_pixel: int,
        xor_mask_data: bytes | None,
        and_mask_data: bytes | None,
        length_xor_mask: int | None = None,
        length_and_mask: int | None = None) -> tuple[bytes, bytes]:

    """Return XOR and AND mask bytes, correcting aardwolf's swapped mask reads."""

    expected_xor_byte_count = \
        compute_expected_xor_mask_byte_count(width, height, xor_bits_per_pixel)
    expected_and_byte_count = compute_expected_and_mask_byte_count(width, height)

    xor_bytes = xor_mask_data or b''
    and_bytes = and_mask_data or b''

    if len(xor_bytes) == expected_xor_byte_count and len(and_bytes) == expected_and_byte_count:
        return xor_bytes, and_bytes

    # aardwolf reads xorMaskData with lengthAndMask and andMaskData with lengthXorMask.
    if len(xor_bytes) == expected_and_byte_count and len(and_bytes) == expected_xor_byte_count:
        return and_bytes, xor_bytes

    if length_xor_mask == expected_xor_byte_count and length_and_mask == expected_and_byte_count:
        if len(xor_bytes) == length_and_mask and len(and_bytes) == length_xor_mask:
            return and_bytes, xor_bytes

    raise ValueError(
        "pointer mask sizes do not match geometry width={width} height={height} xor_bpp={xor_bpp}: "
        "xor_len={xor_len} and_len={and_len} expected_xor={expected_xor} expected_and={expected_and}".format(
            width=width,
            height=height,
            xor_bpp=xor_bits_per_pixel,
            xor_len=len(xor_bytes),
            and_len=len(and_bytes),
            expected_xor=expected_xor_byte_count,
            expected_and=expected_and_byte_count))


def compute_xor_scanline_byte_count(width: int, xor_bits_per_pixel: int) -> int:
    """Return padded XOR mask bytes per scanline."""

    if xor_bits_per_pixel == 1:
        scanline_byte_count = (width + 7) // 8
    else:
        xor_bytes_per_pixel = xor_bits_per_pixel // 8
        scanline_byte_count = width * xor_bytes_per_pixel

    if scanline_byte_count % 2 != 0:
        scanline_byte_count = scanline_byte_count + 1

    return scanline_byte_count


def build_rgba_image_from_pointer_masks(
        width: int,
        height: int,
        xor_bits_per_pixel: int,
        xor_mask_data: bytes,
        and_mask_data: bytes) -> PIL.Image.Image:

    """Decode MS-RDPBCGR xor/and pointer masks into a top-down RGBA image."""

    rgba_image, _invert_mask_image = build_pointer_images_from_pointer_masks(
        width,
        height,
        xor_bits_per_pixel,
        xor_mask_data,
        and_mask_data)

    return rgba_image


def build_pointer_images_from_pointer_masks(
        width: int,
        height: int,
        xor_bits_per_pixel: int,
        xor_mask_data: bytes,
        and_mask_data: bytes) -> tuple[PIL.Image.Image, PIL.Image.Image]:

    """Decode MS-RDPBCGR xor/and masks into RGBA and an invert mask for compositing."""

    rgba_pixels = []
    invert_pixels = []
    and_scanline_byte_count = compute_and_scanline_byte_count(width)
    xor_scanline_byte_count = compute_xor_scanline_byte_count(width, xor_bits_per_pixel)
    xor_bytes_per_pixel = xor_bits_per_pixel // 8

    for y_position in range(height):
        # Color xor/and scanlines are bottom-up; 1-bpp monochrome is top-down (ironrdp/MS).
        if xor_bits_per_pixel == 1:
            source_y_position = y_position
        else:
            source_y_position = height - y_position - 1
        and_scanline_offset = source_y_position * and_scanline_byte_count
        xor_scanline_offset = source_y_position * xor_scanline_byte_count
        and_bit_mask = 0x80
        xor_bit_mask = 0x80
        and_byte_index = and_scanline_offset
        xor_byte_index = xor_scanline_offset

        for x_position in range(width):
            and_pixel = 0
            if and_mask_data is not None and len(and_mask_data) > 0:
                and_pixel = 1 if (and_mask_data[and_byte_index] & and_bit_mask) else 0
                and_bit_mask = and_bit_mask >> 1
                if and_bit_mask == 0:
                    and_bit_mask = 0x80
                    and_byte_index = and_byte_index + 1

            red = 0
            green = 0
            blue = 0
            alpha = 255
            invert_pixel = 0

            if xor_bits_per_pixel == 1:
                xor_pixel = 1 if (xor_mask_data[xor_byte_index] & xor_bit_mask) else 0
                xor_bit_mask = xor_bit_mask >> 1
                if xor_bit_mask == 0:
                    xor_bit_mask = 0x80
                    xor_byte_index = xor_byte_index + 1

                if and_pixel == 0 and xor_pixel == 0:
                    red, green, blue = 0, 0, 0
                elif and_pixel == 0 and xor_pixel == 1:
                    red, green, blue = 255, 255, 255
                elif and_pixel == 1 and xor_pixel == 0:
                    alpha = 0
                else:
                    alpha = 0
                    invert_pixel = 255

            else:
                color_offset = xor_byte_index
                if xor_bits_per_pixel == 32:
                    blue = xor_mask_data[color_offset]
                    green = xor_mask_data[color_offset + 1]
                    red = xor_mask_data[color_offset + 2]
                    alpha = xor_mask_data[color_offset + 3]
                elif xor_bits_per_pixel == 24:
                    blue = xor_mask_data[color_offset]
                    green = xor_mask_data[color_offset + 1]
                    red = xor_mask_data[color_offset + 2]
                elif xor_bits_per_pixel == 16:
                    color_word = \
                        xor_mask_data[color_offset] | (xor_mask_data[color_offset + 1] << 8)
                    red = ((color_word >> 10) & 0x1F) * 255 // 31
                    green = ((color_word >> 5) & 0x1F) * 255 // 31
                    blue = (color_word & 0x1F) * 255 // 31
                else:
                    palette_index = xor_mask_data[color_offset]
                    red = palette_index
                    green = palette_index
                    blue = palette_index

                if and_pixel == 1:
                    if xor_bits_per_pixel == 32:
                        argb_color_value = (
                            (alpha << 24)
                            | (red << 16)
                            | (green << 8)
                            | blue)

                        if argb_color_value == 0xFF000000:
                            alpha = 0
                        elif argb_color_value == 0xFFFFFFFF:
                            alpha = 0
                            invert_pixel = 255
                        else:
                            alpha = 0
                    elif red == 0 and green == 0 and blue == 0:
                        alpha = 0
                    elif red == 255 and green == 255 and blue == 255:
                        alpha = 0
                        invert_pixel = 255
                    else:
                        alpha = 0
                elif xor_bits_per_pixel != 32:
                    alpha = 255

                xor_byte_index = xor_byte_index + xor_bytes_per_pixel

            rgba_pixels.append((red, green, blue, alpha))
            invert_pixels.append(invert_pixel)

    rgba_image = PIL.Image.new("RGBA", (width, height))
    rgba_image.putdata(rgba_pixels)

    invert_mask_image = PIL.Image.new("L", (width, height))
    invert_mask_image.putdata(invert_pixels)

    return rgba_image, invert_mask_image


def fixup_24bpp_rgba_image_from_missing_and_mask(
        rgba_image: PIL.Image.Image) -> PIL.Image.Image:
    """Treat black matte pixels as transparent when a 24-bpp AND mask is absent."""

    rgba_pixels = []

    for red, green, blue, alpha in rgba_image.getdata():
        if red == 0 and green == 0 and blue == 0:
            rgba_pixels.append((0, 0, 0, 0))
        else:
            rgba_pixels.append((red, green, blue, alpha))

    rgba_image.putdata(rgba_pixels)

    return rgba_image


def count_pointer_image_visible_pixels(
        image: PIL.Image.Image,
        invert_mask_image: PIL.Image.Image | None = None) -> int:
    """Return how many pointer pixels are opaque or marked for framebuffer inversion."""

    visible_pixel_count = 0
    rgba_pixels = image.getdata()

    if invert_mask_image is None:
        for red, green, blue, alpha in rgba_pixels:
            if alpha > 0:
                visible_pixel_count = visible_pixel_count + 1

        return visible_pixel_count

    invert_pixels = invert_mask_image.getdata()

    for rgba_pixel, invert_pixel in zip(rgba_pixels, invert_pixels):
        red, green, blue, alpha = rgba_pixel

        if alpha > 0 or invert_pixel:
            visible_pixel_count = visible_pixel_count + 1

    return visible_pixel_count


def pointer_image_has_visible_pixels(
        image: PIL.Image.Image,
        invert_mask_image: PIL.Image.Image | None = None) -> bool:
    """Return True when a decoded pointer image has at least one visible pixel."""

    return count_pointer_image_visible_pixels(image, invert_mask_image) > 0


def build_composited_pointer_rgba_image(
        rgba_image: PIL.Image.Image,
        invert_mask_image: PIL.Image.Image | None,
        cursor_top_left_widget_x: int,
        cursor_top_left_widget_y: int,
        sample_framebuffer_red_green_blue) -> PIL.Image.Image:
    """Composite pointer RGBA with framebuffer-inverted pixels for MS-RDPBCGR invert bits."""

    pointer_width, pointer_height = rgba_image.size
    rgba_pixels = rgba_image.getdata()

    if invert_mask_image is None:
        invert_pixels = [0] * (pointer_width * pointer_height)
    else:
        invert_pixels = invert_mask_image.getdata()

    composited_pixels = []

    for y_position in range(pointer_height):
        for x_position in range(pointer_width):
            pixel_index = y_position * pointer_width + x_position
            red, green, blue, alpha = rgba_pixels[pixel_index]
            invert_pixel = invert_pixels[pixel_index]

            if invert_pixel:
                widget_x = cursor_top_left_widget_x + x_position
                widget_y = cursor_top_left_widget_y + y_position
                frame_sample = sample_framebuffer_red_green_blue(widget_x, widget_y)

                if frame_sample is None:
                    background_red = 0
                    background_green = 0
                    background_blue = 0
                else:
                    background_red, background_green, background_blue = frame_sample

                composited_pixels.append((
                    255 - background_red,
                    255 - background_green,
                    255 - background_blue,
                    255))

            elif alpha > 0:
                composited_pixels.append((red, green, blue, alpha))

            else:
                composited_pixels.append((0, 0, 0, 0))

    composited_image = PIL.Image.new("RGBA", (pointer_width, pointer_height))
    composited_image.putdata(composited_pixels)

    return composited_image


def clamp_hotspot(hotspot_x: int, hotspot_y: int, width: int, height: int) -> tuple[int, int]:
    """Clamp invalid server hotspots to zero per common RDP client behavior."""

    clamped_hotspot_x = hotspot_x
    clamped_hotspot_y = hotspot_y

    if clamped_hotspot_x >= width:
        clamped_hotspot_x = 0

    if clamped_hotspot_y >= height:
        clamped_hotspot_y = 0

    return clamped_hotspot_x, clamped_hotspot_y


def build_bitmap_pointer_update_from_color_attribute(
        color_pointer_attribute,
        xor_bits_per_pixel: int,
        pointer_cache: RdpPointerCache | None = None,
        color_update_data: bytes | None = None) -> RdpPointerUpdate:

    """Build a bitmap pointer update from a TS_FP_COLORPOINTERATTRIBUTE."""

    if color_update_data is not None:
        cache_index, hotspot_x, hotspot_y, width, height, xor_mask_data, and_mask_data = \
            parse_color_pointer_update_data(color_update_data, xor_bits_per_pixel)

        xor_mask_data, and_mask_data = extract_pointer_mask_bytes(
            width,
            height,
            xor_bits_per_pixel,
            xor_mask_data,
            and_mask_data)

    else:
        cache_index = color_pointer_attribute.cacheIndex
        width = color_pointer_attribute.width
        height = color_pointer_attribute.height
        hotspot_x = color_pointer_attribute.hotSpot.xPos
        hotspot_y = color_pointer_attribute.hotSpot.yPos

        xor_mask_data, and_mask_data = extract_pointer_mask_bytes(
            width,
            height,
            xor_bits_per_pixel,
            color_pointer_attribute.xorMaskData,
            color_pointer_attribute.andMaskData,
            color_pointer_attribute.lengthXorMask,
            color_pointer_attribute.lengthAndMask)

    hotspot_x, hotspot_y = clamp_hotspot(hotspot_x, hotspot_y, width, height)

    rgba_image, invert_mask_image = build_pointer_images_from_pointer_masks(
        width,
        height,
        xor_bits_per_pixel,
        xor_mask_data,
        and_mask_data)

    if xor_bits_per_pixel == 24:
        pixel_area = width * height

        if are_all_and_mask_bytes_zero(and_mask_data, width, height) \
                or count_pointer_image_visible_pixels(
                    rgba_image,
                    invert_mask_image) > (pixel_area * 3) // 4:
            rgba_image = fixup_24bpp_rgba_image_from_missing_and_mask(rgba_image)

    pointer_update = RdpPointerUpdate.build_bitmap(
        hotspot_x,
        hotspot_y,
        rgba_image,
        cache_index=cache_index,
        xor_bits_per_pixel=xor_bits_per_pixel,
        invert_mask_image=invert_mask_image)

    if pointer_cache is not None:
        pointer_cache.store_bitmap(cache_index, pointer_update)

    return pointer_update


def build_bitmap_pointer_update_from_large_attribute(
        large_pointer_attribute,
        pointer_cache: RdpPointerCache | None = None,
        large_pointer_update_data: bytes | None = None) -> RdpPointerUpdate:

    """Build a bitmap pointer update from a TS_FP_LARGEPOINTERATTRIBUTE."""

    if large_pointer_update_data is not None:
        buffer = io.BytesIO(large_pointer_update_data)
        xor_bits_per_pixel = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
        cache_index = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
        hotspot_x = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
        hotspot_y = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
        width = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
        height = int.from_bytes(buffer.read(2), byteorder="little", signed=False)
        length_and_mask = int.from_bytes(buffer.read(4), byteorder="little", signed=False)
        length_xor_mask = int.from_bytes(buffer.read(4), byteorder="little", signed=False)
        xor_mask_data = buffer.read(length_xor_mask)
        and_mask_data = buffer.read(length_and_mask)

    else:
        xor_bits_per_pixel = large_pointer_attribute.xorBpp
        cache_index = large_pointer_attribute.cacheIndex
        width = large_pointer_attribute.width
        height = large_pointer_attribute.height
        hotspot_x = large_pointer_attribute.hotSpot.xPos
        hotspot_y = large_pointer_attribute.hotSpot.yPos

        xor_mask_data, and_mask_data = extract_pointer_mask_bytes(
            width,
            height,
            large_pointer_attribute.xorBpp,
            large_pointer_attribute.xorMaskData,
            large_pointer_attribute.andMaskData,
            large_pointer_attribute.lengthXorMask,
            large_pointer_attribute.lengthAndMask)

    hotspot_x, hotspot_y = clamp_hotspot(hotspot_x, hotspot_y, width, height)

    rgba_image, invert_mask_image = build_pointer_images_from_pointer_masks(
        width,
        height,
        xor_bits_per_pixel,
        xor_mask_data,
        and_mask_data)

    if xor_bits_per_pixel == 24:
        pixel_area = width * height

        if are_all_and_mask_bytes_zero(and_mask_data, width, height) \
                or count_pointer_image_visible_pixels(
                    rgba_image,
                    invert_mask_image) > (pixel_area * 3) // 4:
            rgba_image = fixup_24bpp_rgba_image_from_missing_and_mask(rgba_image)

    pointer_update = RdpPointerUpdate.build_bitmap(
        hotspot_x,
        hotspot_y,
        rgba_image,
        cache_index=cache_index,
        xor_bits_per_pixel=xor_bits_per_pixel,
        invert_mask_image=invert_mask_image)

    if pointer_cache is not None:
        pointer_cache.store_bitmap(cache_index, pointer_update)

    return pointer_update
