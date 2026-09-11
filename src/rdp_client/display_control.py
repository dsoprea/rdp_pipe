"""MS-RDPEDISP display control dynamic virtual channel (RDPDISP)."""

import asyncio
import struct

import aardwolf.extensions.RDPEDYC.vchannels


DISPLAY_CONTROL_CHANNEL_NAME = "Microsoft::Windows::RDS::DisplayControl"

PDU_TYPE_MONITOR_LAYOUT = 0x00000002
PDU_TYPE_CAPS = 0x00000005

MONITOR_LAYOUT_STRUCT_SIZE = 40
MONITOR_PRIMARY_FLAG = 0x00000001

MIN_DISPLAY_WIDTH = 200
MAX_DISPLAY_WIDTH = 8192
MIN_DISPLAY_HEIGHT = 200
MAX_DISPLAY_HEIGHT = 8192

DEFAULT_PHYSICAL_WIDTH_MILLIMETERS = 508
DEFAULT_PHYSICAL_HEIGHT_MILLIMETERS = 286
DEFAULT_ORIENTATION = 0
DEFAULT_DESKTOP_SCALE_FACTOR = 100
DEFAULT_DEVICE_SCALE_FACTOR = 100


class DisplayControlCaps:
    """Server-advertised RDPDISP capabilities from DISPLAYCONTROL_CAPS_PDU."""

    def __init__(
            self,
            max_num_monitors: int,
            max_monitor_area_factor_a: int,
            max_monitor_area_factor_b: int):

        self.max_num_monitors = max_num_monitors
        self.max_monitor_area_factor_a = max_monitor_area_factor_a
        self.max_monitor_area_factor_b = max_monitor_area_factor_b


def clamp_even_display_width(width: int) -> int:
    """Clamp width to RDPDISP bounds and force an even value."""

    clamped_width = width
    if clamped_width < MIN_DISPLAY_WIDTH:
        clamped_width = MIN_DISPLAY_WIDTH
    if clamped_width > MAX_DISPLAY_WIDTH:
        clamped_width = MAX_DISPLAY_WIDTH

    if clamped_width % 2 != 0:
        clamped_width = clamped_width - 1

    return clamped_width


def clamp_display_height(height: int) -> int:
    """Clamp height to RDPDISP bounds."""

    clamped_height = height
    if clamped_height < MIN_DISPLAY_HEIGHT:
        clamped_height = MIN_DISPLAY_HEIGHT
    if clamped_height > MAX_DISPLAY_HEIGHT:
        clamped_height = MAX_DISPLAY_HEIGHT

    return clamped_height


def build_monitor_layout_bytes(
        width: int,
        height: int,
        is_primary: bool = True) -> bytes:
    """Encode one DISPLAYCONTROL_MONITOR_LAYOUT (40 bytes)."""

    even_width = clamp_even_display_width(width)
    clamped_height = clamp_display_height(height)

    flags = 0
    if is_primary:
        flags = MONITOR_PRIMARY_FLAG

    layout_bytes = struct.pack(
        "<iiiiiiiiii",
        flags,
        0,
        0,
        even_width,
        clamped_height,
        DEFAULT_PHYSICAL_WIDTH_MILLIMETERS,
        DEFAULT_PHYSICAL_HEIGHT_MILLIMETERS,
        DEFAULT_ORIENTATION,
        DEFAULT_DESKTOP_SCALE_FACTOR,
        DEFAULT_DEVICE_SCALE_FACTOR)

    return layout_bytes


def encode_monitor_layout_pdu(width: int, height: int) -> bytes:
    """Encode DISPLAYCONTROL_MONITOR_LAYOUT_PDU for a single primary monitor."""

    monitor_layout_bytes = build_monitor_layout_bytes(width, height)
    pdu_length = 8 + 8 + MONITOR_LAYOUT_STRUCT_SIZE

    pdu_bytes = struct.pack(
        "<IIII",
        PDU_TYPE_MONITOR_LAYOUT,
        pdu_length,
        MONITOR_LAYOUT_STRUCT_SIZE,
        1)

    pdu_bytes = pdu_bytes + monitor_layout_bytes

    return pdu_bytes


def decode_caps_pdu(data: bytes) -> DisplayControlCaps:
    """Decode DISPLAYCONTROL_CAPS_PDU from channel payload bytes."""

    if len(data) < 20:
        raise ValueError(
            "DISPLAYCONTROL_CAPS_PDU shorter than 20 bytes (length={length})".format(
                length=len(data)))

    message_type, pdu_length = struct.unpack("<II", data[0:8])

    if message_type != PDU_TYPE_CAPS:
        raise ValueError(
            "expected DISPLAYCONTROL_CAPS_PDU type {expected}, got {actual}".format(
                expected=PDU_TYPE_CAPS,
                actual=message_type))

    if pdu_length < 20:
        raise ValueError(
            "DISPLAYCONTROL_CAPS_PDU length field too small (length={length})".format(
                length=pdu_length))

    max_num_monitors, factor_a, factor_b = struct.unpack("<III", data[8:20])

    caps = DisplayControlCaps(
        max_num_monitors,
        factor_a,
        factor_b)

    return caps


class DisplayControlChannel(aardwolf.extensions.RDPEDYC.vchannels.VirtualChannelBase):
    """RDPDISP client channel for seamless remote resolution changes."""

    def __init__(self, resolution_request_callback=None):
        """Register callbacks; resolution_request_callback(width, height) is optional."""

        aardwolf.extensions.RDPEDYC.vchannels.VirtualChannelBase.__init__(
            self,
            DISPLAY_CONTROL_CHANNEL_NAME)

        self._caps: DisplayControlCaps | None = None
        self._caps_received_event = asyncio.Event()
        self._resolution_request_callback = resolution_request_callback
        self._caps_missing_logged = False

    def set_resolution_request_callback(self, resolution_request_callback):
        """Attach callback(width, height) invoked after a layout PDU is sent."""

        self._resolution_request_callback = resolution_request_callback

    @property
    def caps_received(self) -> bool:
        """True after the server sends DISPLAYCONTROL_CAPS_PDU."""

        return self._caps is not None

    async def channel_init(self):
        """Accept channel creation; caps arrive asynchronously."""

        return True, None

    async def channel_data_in(self, data: bytes):
        """Handle incoming RDPDISP PDUs from the server."""

        if len(data) < 4:
            return

        message_type = struct.unpack("<I", data[0:4])[0]

        if message_type == PDU_TYPE_CAPS:
            self._caps = decode_caps_pdu(data)
            self._caps_received_event.set()

    async def wait_for_caps(self, timeout_seconds: float) -> bool:
        """Wait until caps arrive or timeout_seconds elapse."""

        try:
            await asyncio.wait_for(
                self._caps_received_event.wait(),
                timeout=timeout_seconds)

            return True

        except asyncio.TimeoutError:
            return False

    async def request_resolution(self, width: int, height: int) -> bool:
        """Send DISPLAYCONTROL_MONITOR_LAYOUT_PDU when caps are available."""

        if self._caps is None:
            if self._caps_missing_logged is False:
                self._caps_missing_logged = True

            return False

        even_width = clamp_even_display_width(width)
        clamped_height = clamp_display_height(height)

        pdu_bytes = encode_monitor_layout_pdu(even_width, clamped_height)
        await self.channel_data_out(pdu_bytes)

        if self._resolution_request_callback is not None:
            self._resolution_request_callback(even_width, clamped_height)

        return True
