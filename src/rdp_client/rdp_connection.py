"""RDPConnection subclass with RDPDISP-oriented capability flags and buffer resize."""

import copy
import logging

import aardwolf.commons.factory
import aardwolf.connection
import aardwolf.protocol.T124.userdata.clientcoredata
import aardwolf.protocol.T124.userdata.constants
import PIL.Image

import rdp_client.display_control


_LOGGER = logging.getLogger(__name__)

_CONNECTING_DESKTOP_CONNECTION = None
_ORIGINAL_TS_UD_CS_CORE_TO_BYTES = \
    aardwolf.protocol.T124.userdata.clientcoredata.TS_UD_CS_CORE.to_bytes


def _patched_ts_ud_cs_core_to_bytes(self):
    """Augment early capability flags while the desktop connection is negotiating."""

    global _CONNECTING_DESKTOP_CONNECTION

    if _CONNECTING_DESKTOP_CONNECTION is not None:
        if self.earlyCapabilityFlags is not None:
            self.earlyCapabilityFlags = (
                self.earlyCapabilityFlags
                | aardwolf.protocol.T124.userdata.constants.RNS_UD_CS.SUPPORT_MONITOR_LAYOUT_PDU
                | aardwolf.protocol.T124.userdata.constants.RNS_UD_CS.WANT_32BPP_SESSION)

            if _CONNECTING_DESKTOP_CONNECTION.iosettings.video_bpp_max == 32:
                self.highColorDepth = \
                    aardwolf.protocol.T124.userdata.constants.HIGH_COLOR_DEPTH.HIGH_COLOR_24BPP

    return _ORIGINAL_TS_UD_CS_CORE_TO_BYTES(self)


aardwolf.protocol.T124.userdata.clientcoredata.TS_UD_CS_CORE.to_bytes = \
    _patched_ts_ud_cs_core_to_bytes


class RdpDesktopConnection(aardwolf.connection.RDPConnection):
    """Desktop RDP session with monitor-layout support and explicit buffer resize."""

    def __init__(self, target, credential, iosettings):
        """Store optional resolution listeners used by the Qt front end."""

        aardwolf.connection.RDPConnection.__init__(self, target, credential, iosettings)

        self.resolution_changed_listeners = []
        self.display_control_channel: rdp_client.display_control.DisplayControlChannel | None = None

    def add_resolution_changed_listener(self, listener):
        """Register listener(width, height) called after the desktop buffer is resized."""

        self.resolution_changed_listeners.append(listener)

    def reallocate_desktop_buffer(self, width: int, height: int):
        """Resize iosettings and the internal PIL desktop buffer."""

        self.iosettings.video_width = width
        self.iosettings.video_height = height

        new_buffer = PIL.Image.new(
            mode="RGBA",
            size=(width, height))

        self._RDPConnection__desktop_buffer = new_buffer
        self.desktop_buffer_has_data = False

        for listener in self.resolution_changed_listeners:
            listener(width, height)

    async def connect(self):
        """Connect while capability-flag patching is active for Client Core Data."""

        global _CONNECTING_DESKTOP_CONNECTION

        _CONNECTING_DESKTOP_CONNECTION = self

        try:
            connect_result = await aardwolf.connection.RDPConnection.connect(self)

            return connect_result

        finally:
            _CONNECTING_DESKTOP_CONNECTION = None

class RdpDesktopConnectionFactory(aardwolf.commons.factory.RDPConnectionFactory):
    """Factory that builds RdpDesktopConnection instead of the stock RDPConnection."""

    def get_connection(self, iosettings):
        """Return a desktop connection using copied target and credential."""

        copied_iosettings = copy.deepcopy(iosettings)
        credential = self.get_credential()
        target = self.get_target()

        if target.dialect is not None:
            import aardwolf.commons.target

            if target.dialect == aardwolf.commons.target.RDPConnectionDialect.RDP:
                return RdpDesktopConnection(target, credential, copied_iosettings)

            if target.dialect == aardwolf.commons.target.RDPConnectionDialect.VNC:
                return aardwolf.vncconnection.VNCConnection(
                    target,
                    credential,
                    copied_iosettings)

            raise Exception("Unknown dialect {dialect}".format(dialect=target.dialect))

        raise Exception("Either target or dialect must be defined first!")


def build_iosettings_with_display_control(
        video_width: int,
        video_height: int,
        resolution_request_callback=None) -> "aardwolf.commons.iosettings.RDPIOSettings":
    """Create iosettings with RDPDISP channel registration and 32 bpp video."""

    import aardwolf.commons.iosettings

    iosettings = aardwolf.commons.iosettings.RDPIOSettings()
    iosettings.video_width = video_width
    iosettings.video_height = video_height
    iosettings.video_bpp_max = 32
    iosettings.video_bpp_min = 16

    display_channel = rdp_client.display_control.DisplayControlChannel(
        resolution_request_callback=resolution_request_callback)

    iosettings.vchannels[
        rdp_client.display_control.DISPLAY_CONTROL_CHANNEL_NAME] = display_channel

    return iosettings, display_channel


async def _rdp_desktop_process_fastpath(self, fpdu):
    """Reallocate the desktop buffer when a full-screen bitmap changes geometry."""

    try:
        import aardwolf.protocol.fastpath
        import aardwolf.commons.queuedata.video

        if fpdu.fpOutputUpdates.updateCode == \
                aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.BITMAP:

            for bitmapdata in fpdu.fpOutputUpdates.update.rectangles:
                bitmap_width = bitmapdata.destRight - bitmapdata.destLeft + 1
                bitmap_height = bitmapdata.destBottom - bitmapdata.destTop + 1

                if bitmapdata.destLeft == 0 \
                        and bitmapdata.destTop == 0 \
                        and (
                            bitmap_width != self.iosettings.video_width
                            or bitmap_height != self.iosettings.video_height):

                    self.reallocate_desktop_buffer(bitmap_width, bitmap_height)

                self.desktop_buffer_has_data = True

                video_rectangle, image = \
                    aardwolf.commons.queuedata.video.RDP_VIDEO.from_bitmapdata(
                        bitmapdata,
                        self.iosettings.video_out_format)

                self._RDPConnection__desktop_buffer.paste(
                    image,
                    [
                        video_rectangle.x,
                        video_rectangle.y,
                        video_rectangle.x + video_rectangle.width,
                        video_rectangle.y + video_rectangle.height,
                    ])

                await self.ext_out_queue.put(video_rectangle)

    except Exception as error:
        _LOGGER.error(
            "fastpath processing failed: {error}".format(error=error))


RdpDesktopConnection._RDPConnection__process_fastpath = _rdp_desktop_process_fastpath
