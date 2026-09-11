"""Test double for RdpDesktopConnection used by session integration tests."""

import asyncio
import struct
import threading

import aardwolf.commons.queuedata.constants
import PIL.Image

import rdp_client.connection_progress
import rdp_client.display_control
import rdp_client.rdp_connection


class MockDisplayControlChannel(rdp_client.display_control.DisplayControlChannel):
    """Display control channel that skips DVC wire I/O in unit tests."""

    def __init__(self, resolution_request_callback=None):
        """Register optional resolution callback like the production channel."""

        rdp_client.display_control.DisplayControlChannel.__init__(
            self,
            resolution_request_callback=resolution_request_callback)

    async def request_resolution(self, width: int, height: int) -> bool:
        """Apply layout locally without channel_data_out."""

        if self._caps is None:
            if self._caps_missing_logged is False:
                self._caps_missing_logged = True

            return False

        even_width = rdp_client.display_control.clamp_even_display_width(width)
        clamped_height = rdp_client.display_control.clamp_display_height(height)

        if self._resolution_request_callback is not None:
            self._resolution_request_callback(even_width, clamped_height)

        return True


def build_display_control_caps_pdu_bytes() -> bytes:
    """Encode a minimal DISPLAYCONTROL_CAPS_PDU for mock channel injection."""

    caps_bytes = struct.pack(
        "<IIIII",
        rdp_client.display_control.PDU_TYPE_CAPS,
        20,
        16,
        8192,
        8192)

    return caps_bytes


class MockRdpConnection:
    """Fake RdpDesktopConnection with asyncio queues and a PIL desktop buffer."""

    def __init__(
            self,
            video_width: int = 1280,
            video_height: int = 800,
            color_depth: int = 32,
            deliver_caps: bool = True,
            desktop_buffer_has_data: bool = True,
            desktop_image: PIL.Image.Image | None = None):

        """Prepare queues, iosettings, and optional framebuffer state."""

        self._video_width = video_width
        self._video_height = video_height
        self._color_depth = color_depth
        self._deliver_caps = deliver_caps
        self._desktop_buffer_has_data = desktop_buffer_has_data
        self._resolution_changed_listeners = []
        self.progress_callback = None
        self.disconnected_evt = threading.Event()
        self.ext_out_queue = asyncio.Queue()
        self.ext_in_queue = asyncio.Queue()

        iosettings, _display_control_channel = \
            rdp_client.rdp_connection.build_iosettings_with_display_control(
                video_width,
                video_height,
                color_depth)

        display_control_channel = MockDisplayControlChannel()
        iosettings.vchannels[
            rdp_client.display_control.DISPLAY_CONTROL_CHANNEL_NAME] = display_control_channel

        self.iosettings = iosettings
        self.display_control_channel = display_control_channel

        if desktop_image is None:
            self._desktop_image = PIL.Image.new(
                "RGBA",
                (video_width, video_height),
                color=(32, 64, 96, 255))
        else:
            self._desktop_image = desktop_image

    def bind_iosettings(self, copied_iosettings):
        """Preserve vchannels identity like RdpDesktopConnectionFactory.get_connection."""

        copied_iosettings.vchannels = self.iosettings.vchannels
        self.iosettings = copied_iosettings
        self.display_control_channel = copied_iosettings.vchannels[
            rdp_client.display_control.DISPLAY_CONTROL_CHANNEL_NAME]

        return self

    @property
    def desktop_buffer_has_data(self) -> bool:
        """True when screenshot capture should succeed."""

        return self._desktop_buffer_has_data

    @desktop_buffer_has_data.setter
    def desktop_buffer_has_data(self, has_data: bool):
        """Allow tests to simulate an empty framebuffer."""

        self._desktop_buffer_has_data = has_data

    def add_resolution_changed_listener(self, listener):
        """Register listener(width, height) after buffer resize."""

        self._resolution_changed_listeners.append(listener)

    def reallocate_desktop_buffer(self, width: int, height: int):
        """Resize iosettings and the internal PIL desktop buffer."""

        self.iosettings.video_width = width
        self.iosettings.video_height = height
        self._video_width = width
        self._video_height = height
        self._desktop_image = PIL.Image.new(
            "RGBA",
            (width, height),
            color=(32, 64, 96, 255))
        self._desktop_buffer_has_data = True

        for listener in self._resolution_changed_listeners:
            listener(width, height)

    def get_desktop_buffer(self, output_format):
        """Return the mock framebuffer when PIL format is requested."""

        if output_format != aardwolf.commons.queuedata.constants.VIDEO_FORMAT.PIL:
            return None

        return self._desktop_image

    async def connect(self):
        """Simulate connect progress without network I/O."""

        if self.progress_callback is not None:
            self.progress_callback(
                rdp_client.connection_progress.CONNECTION_STEP_CONNECTING)

        return True, None

    async def open_display_control_channel(self) -> bool:
        """Deliver RDPDISP caps when configured."""

        if self._deliver_caps is False:
            return True

        caps_pdu_bytes = build_display_control_caps_pdu_bytes()
        await self.display_control_channel.channel_data_in(caps_pdu_bytes)

        return True

    async def terminate(self):
        """Signal the output loop to stop."""

        await self.ext_out_queue.put(None)
