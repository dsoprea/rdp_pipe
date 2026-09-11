"""Qt-free asyncio RDP session with command handlers for automation."""

import asyncio
import base64
import io
import logging
import aardwolf.commons.queuedata
import aardwolf.commons.queuedata.constants
import PIL.Image

import rdp_client.rdp_connection
import rdp_client.rdp_input


_LOGGER = logging.getLogger(__name__)

DISPLAY_CONTROL_CAPS_TIMEOUT_SECONDS = 10.0
COMMAND_HANDLER_TIMEOUT_SECONDS = 30.0


class RdpSessionError(Exception):
    """Raised when a session command cannot be completed."""


class RdpVideoFrame:
    """Partial framebuffer update from the RDP session."""

    def __init__(self, x_position, y_position, image, width, height):
        """Store rectangle metadata and a PIL image patch."""

        self.x_position = x_position
        self.y_position = y_position
        self.image = image
        self.width = width
        self.height = height


class RdpAsyncSession:
    """Manage an aardwolf RDP connection on an asyncio event loop."""

    def __init__(
            self,
            connection_url: str,
            video_width: int,
            video_height: int):

        """Prepare session state; call connect and run_until_stopped."""

        self._connection_url = connection_url
        self._video_width = video_width
        self._video_height = video_height
        self._iosettings = None
        self._display_control_channel = None
        self._connection = None
        self._stop_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._display_caps_unavailable = False
        self._resolution_changed_callbacks = []
        self._video_frame_callbacks = []

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop | None:
        """Return the asyncio loop when the session task is running."""

        try:
            return asyncio.get_running_loop()

        except RuntimeError:
            return None

    @property
    def connection(self):
        """Return the underlying RdpDesktopConnection after connect."""

        return self._connection

    @property
    def iosettings(self):
        """Return RDPIOSettings for this session."""

        return self._iosettings

    @property
    def display_control_channel(self):
        """Return the RDPDISP channel registered in iosettings."""

        return self._display_control_channel

    @property
    def is_connected(self) -> bool:
        """True after connect() succeeds."""

        return self._connected_event.is_set()

    @property
    def display_caps_unavailable(self) -> bool:
        """True when RDPDISP caps never arrived during connect."""

        return self._display_caps_unavailable

    def add_resolution_changed_callback(self, callback):
        """Register callback(width, height) after buffer reallocation."""

        self._resolution_changed_callbacks.append(callback)

    def add_video_frame_callback(self, callback):
        """Register callback(RdpVideoFrame) for each VIDEO rectangle."""

        self._video_frame_callbacks.append(callback)

    async def connect(self):
        """Establish the RDP connection and wait for RDPDISP caps."""

        iosettings, display_control_channel = \
            rdp_client.rdp_connection.build_iosettings_with_display_control(
                self._video_width,
                self._video_height)

        self._iosettings = iosettings
        self._display_control_channel = display_control_channel

        connection_factory = \
            rdp_client.rdp_connection.RdpDesktopConnectionFactory.from_url(
                self._connection_url,
                self._iosettings)

        self._connection = connection_factory.get_connection(self._iosettings)
        self._connection.display_control_channel = self._display_control_channel

        self._display_control_channel.set_resolution_request_callback(
            self._reallocate_desktop_buffer_for_resolution_request)

        self._connection.add_resolution_changed_listener(self._notify_resolution_changed)

        connect_ok, connect_error = await self._connection.connect()
        if connect_error is not None:
            raise connect_error

        if connect_ok is None:
            raise RdpSessionError("RDP connection failed without an error detail")

        await self._connection.open_display_control_channel()

        caps_available = await self._display_control_channel.wait_for_caps(
            DISPLAY_CONTROL_CAPS_TIMEOUT_SECONDS)

        if caps_available is False:
            self._display_caps_unavailable = True
            _LOGGER.warning(
                "RDPDISP caps not received; seamless resize disabled for this server")

        self._connected_event.set()

    def _reallocate_desktop_buffer_for_resolution_request(self, width: int, height: int):
        """Resize the desktop buffer when RDPDISP accepts a layout request."""

        if self._connection is None:
            return

        self._connection.reallocate_desktop_buffer(width, height)

    def _notify_resolution_changed(self, width: int, height: int):
        """Invoke resolution callbacks registered by GUI or automation."""

        for callback in self._resolution_changed_callbacks:
            callback(width, height)

    async def run_until_stopped(self):
        """Drain ext_out_queue until stop() or disconnect."""

        while not self._stop_event.is_set():
            output_item = await self._connection.ext_out_queue.get()
            if output_item is None:
                return

            if output_item.type == aardwolf.commons.queuedata.RDPDATATYPE.VIDEO:
                video_frame = RdpVideoFrame(
                    output_item.x,
                    output_item.y,
                    output_item.data,
                    output_item.width,
                    output_item.height)

                for callback in self._video_frame_callbacks:
                    callback(video_frame)

                if self._stop_event.is_set():
                    return

    async def stop(self):
        """Signal the output loop to exit and terminate the connection."""

        self._stop_event.set()

        if self._connection is not None:
            await self._connection.terminate()

    async def request_remote_resolution(self, width: int, height: int):
        """Send DISPLAYCONTROL_MONITOR_LAYOUT_PDU when caps are available."""

        await self._display_control_channel.request_resolution(width, height)

    async def enqueue_input_messages(self, messages: list):
        """Put input messages on ext_in_queue."""

        for message in messages:
            await self._connection.ext_in_queue.put(message)

    async def handle_receive_geometry(self) -> dict:
        """Return remote session width, height, and color depth."""

        return {
            "width": self._iosettings.video_width,
            "height": self._iosettings.video_height,
            "color_depth": self._iosettings.video_bpp_max,
        }

    async def handle_receive_screenshot(
            self,
            image_format: str = "png",
            quality: int = 9) -> dict:

        """Capture the remote framebuffer and return base64-encoded image bytes."""

        if self._connection.desktop_buffer_has_data is False:
            raise RdpSessionError("desktop buffer has no image data yet")

        desktop_image = self._connection.get_desktop_buffer(
            aardwolf.commons.queuedata.constants.VIDEO_FORMAT.PIL)

        if desktop_image is None:
            raise RdpSessionError("desktop buffer could not be read")

        normalized_format = image_format.lower()
        image_bytes = encode_desktop_image(
            desktop_image,
            normalized_format,
            quality)

        encoded_data = base64.standard_b64encode(image_bytes).decode("ascii")

        return {
            "width": self._iosettings.video_width,
            "height": self._iosettings.video_height,
            "format": normalized_format,
            "data": encoded_data,
        }

    async def handle_send_click(self, x_position: int, y_position: int, button: str) -> dict:
        """Send a mouse click at remote coordinates."""

        click_messages = rdp_client.rdp_input.build_mouse_click_messages(
            x_position,
            y_position,
            button)

        await self.enqueue_input_messages(click_messages)

        return {}

    async def handle_send_key(self, keys: str | None = None, key: str | None = None) -> dict:
        """Send keyboard input as text or a named key."""

        if keys is not None and key is not None:
            raise rdp_client.rdp_input.RdpInputError("send_key accepts keys or key, not both")

        if keys is None and key is None:
            raise rdp_client.rdp_input.RdpInputError("send_key requires keys or key")

        if keys is not None:
            key_messages = rdp_client.rdp_input.build_text_key_messages(keys)
        else:
            key_messages = rdp_client.rdp_input.build_named_key_messages(key)

        await self.enqueue_input_messages(key_messages)

        return {}


def encode_desktop_image(
        desktop_image: PIL.Image.Image,
        image_format: str,
        quality: int) -> bytes:

    """Encode a PIL desktop buffer as PNG or JPEG bytes."""

    if image_format not in ("png", "jpeg", "jpg"):
        raise RdpSessionError(
            "unsupported image format {image_format}; use png or jpeg".format(
                image_format=image_format))

    rgb_image = desktop_image.convert("RGB")
    output_buffer = io.BytesIO()

    if image_format == "png":
        compress_level = quality
        if compress_level < 0:
            compress_level = 0
        if compress_level > 9:
            compress_level = 9

        rgb_image.save(
            output_buffer,
            format="PNG",
            compress_level=compress_level)

    else:
        jpeg_quality = quality
        if jpeg_quality < 1:
            jpeg_quality = 1
        if jpeg_quality > 95:
            jpeg_quality = 95

        rgb_image.save(
            output_buffer,
            format="JPEG",
            quality=jpeg_quality)

    return output_buffer.getvalue()

