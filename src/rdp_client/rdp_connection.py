"""RDPConnection subclass with RDPDISP-oriented capability flags and buffer resize."""

import copy
import datetime
import logging

import aardwolf.commons.factory
import aardwolf.connection
import aardwolf.extensions.RDPEDYC.channel
import aardwolf.extensions.RDPEDYC.protocol
import aardwolf.extensions.RDPEDYC.protocol.create
import aardwolf.protocol.T124.userdata.clientcoredata
import aardwolf.protocol.T124.userdata.constants
import PIL.Image

import rdp_client.connection_progress
import rdp_client.display_control
import rdp_client.trust_store


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


class RdpEdycChannel(aardwolf.extensions.RDPEDYC.channel.RDPEDYCChannel):
    """Dynamic virtual channel manager with client-initiated channel open."""

    def __init__(self, iosettings):
        """Track pending client channel create requests."""

        aardwolf.extensions.RDPEDYC.channel.RDPEDYCChannel.__init__(self, iosettings)

        self._next_client_channel_id = 1000
        self._pending_client_channel_names_by_id: dict[int, str] = {}

    async def open_virtual_channel(self, channel_name: str) -> bool:
        """Send a DYNVC create request for a registered virtual channel."""

        if channel_name not in self.defined_channels:
            return False

        virtual_channel = self.defined_channels[channel_name]

        if virtual_channel.channel_id is not None:
            return True

        create_request = aardwolf.extensions.RDPEDYC.protocol.create.DYNVC_CREATE_REQ()
        create_request.ChannelId = self._next_client_channel_id
        create_request.ChannelName = channel_name

        self._pending_client_channel_names_by_id[create_request.ChannelId] = channel_name
        self._next_client_channel_id = self._next_client_channel_id + 1

        await self.fragment_and_send(create_request.to_bytes())

        return True

    async def process_channel_data(self, data):
        """Handle server create requests and create responses to client opens."""

        import aardwolf.protocol.channelpdu

        channel_data = aardwolf.protocol.channelpdu.CHANNEL_PDU_HEADER.from_bytes(data)
        message = aardwolf.extensions.RDPEDYC.protocol.DYNVC_MESSAGE.from_bytes(channel_data.data)

        if message.cmd == aardwolf.extensions.RDPEDYC.protocol.DYNVC_CMD.CREATE_RSP:
            create_response = \
                aardwolf.extensions.RDPEDYC.protocol.create.DYNVC_CREATE_RSP.from_bytes(
                    channel_data.data)

            pending_channel_name = \
                self._pending_client_channel_names_by_id.get(create_response.ChannelId)

            if pending_channel_name is not None:
                if create_response.CreationStatus != 0:
                    del self._pending_client_channel_names_by_id[create_response.ChannelId]

                    return

                virtual_channel = self.defined_channels[pending_channel_name]
                del self._pending_client_channel_names_by_id[create_response.ChannelId]

                _, init_error = await virtual_channel.channel_init_internal(
                    create_response.ChannelId,
                    self)

                if init_error is not None:
                    return

                self.channels[create_response.ChannelId] = virtual_channel

                return

        await aardwolf.extensions.RDPEDYC.channel.RDPEDYCChannel.process_channel_data(
            self,
            data)


class RdpDesktopConnection(aardwolf.connection.RDPConnection):
    """Desktop RDP session with monitor-layout support and explicit buffer resize."""

    def __init__(self, target, credential, iosettings):
        """Store optional resolution listeners used by the Qt front end."""

        aardwolf.connection.RDPConnection.__init__(self, target, credential, iosettings)

        self.resolution_changed_listeners = []
        self.display_control_channel: rdp_client.display_control.DisplayControlChannel | None = None
        self.progress_callback = None

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

    async def open_display_control_channel(self) -> bool:
        """Open RDPDISP when the server has not already created the channel."""

        if self.display_control_channel is None:
            return False

        if self.display_control_channel.channel_id is not None:
            return True

        dynamic_channel = self._RDPConnection__joined_channels.get("drdynvc")

        if dynamic_channel is None:
            return False

        open_virtual_channel = getattr(dynamic_channel, "open_virtual_channel", None)

        if open_virtual_channel is None:
            return False

        return await open_virtual_channel(
            rdp_client.display_control.DISPLAY_CONTROL_CHANNEL_NAME)

    def _report_connection_progress(self, step_identifier: str):
        """Invoke the optional GUI progress callback for a connect step."""

        if self.progress_callback is None:
            return

        self.progress_callback(step_identifier)

    async def connect(self):
        """Connect while capability-flag patching is active for Client Core Data."""

        global _CONNECTING_DESKTOP_CONNECTION

        _CONNECTING_DESKTOP_CONNECTION = self

        try:
            self._report_connection_progress(
                rdp_client.connection_progress.CONNECTION_STEP_CONNECTING)

            connect_result = await aardwolf.connection.RDPConnection.connect(self)

            return connect_result

        finally:
            _CONNECTING_DESKTOP_CONNECTION = None


    def _get_capability_exchange_data_start_offset(self) -> int:
        """Return the MCS payload offset when server encryption level is 1."""

        import aardwolf.protocol.T124.userdata.constants

        data_start_offset = 0

        if self._RDPConnection__server_connect_pdu[
                aardwolf.protocol.T124.userdata.constants.TS_UD_TYPE.SC_SECURITY].encryptionLevel == 1:
            data_start_offset = 4

        return data_start_offset

    async def _await_synchronize_after_confirm_active(self, data_start_offset: int):
        """Read MCS replies until SYNCHRONIZE, skipping MONITOR_LAYOUT_PDU."""

        import aardwolf.protocol.T128.clientconfirmactivepdu
        import aardwolf.protocol.T128.seterrorinfopdu
        import aardwolf.protocol.T128.share
        import aardwolf.protocol.T128.synchronizepdu

        while True:
            data, err = await self._RDPConnection__joined_channels["MCS"].out_queue.get()

            if err is not None:
                raise err

            data = data[data_start_offset:]
            share_control_header =                 aardwolf.protocol.T128.clientconfirmactivepdu.TS_SHARECONTROLHEADER.from_bytes(data)

            if share_control_header.pduType != aardwolf.protocol.T128.share.PDUTYPE.DATAPDU:
                raise Exception(
                    "Unexpected reply! {pdu_type}".format(
                        pdu_type=share_control_header.pduType.name))

            share_data_header = aardwolf.protocol.T128.inputeventpdu.TS_SHAREDATAHEADER.from_bytes(data)

            if share_data_header.pduType2 == aardwolf.protocol.T128.share.PDUTYPE2.SET_ERROR_INFO_PDU:
                error_pdu = aardwolf.protocol.T128.seterrorinfopdu.TS_SET_ERROR_INFO_PDU.from_bytes(data)

                raise Exception(
                    "Server replied with error! Code: {code} ErrName: {error_name}".format(
                        code=hex(error_pdu.errorInfoRaw),
                        error_name=error_pdu.errorInfo.name))

            if share_data_header.pduType2 == aardwolf.protocol.T128.share.PDUTYPE2.SYNCHRONIZE:
                aardwolf.protocol.T128.synchronizepdu.TS_SYNCHRONIZE_PDU.from_bytes(data)

                return

            if share_data_header.pduType2 == aardwolf.protocol.T128.share.PDUTYPE2.MONITOR_LAYOUT_PDU:
                continue

            raise Exception(
                "Unexpected reply! {pdu_type}".format(
                    pdu_type=share_data_header.pduType2.name))

    async def _finish_mandatory_capability_exchange_after_synchronize(self):
        """Send client synchronize, control, and font-list PDUs after server synchronize."""

        import aardwolf.protocol.T128.controlpdu
        import aardwolf.protocol.T128.fontlistpdu
        import aardwolf.protocol.T128.inputeventpdu
        import aardwolf.protocol.T128.security
        import aardwolf.protocol.T128.share
        import aardwolf.protocol.T128.synchronizepdu

        data_header = aardwolf.protocol.T128.inputeventpdu.TS_SHAREDATAHEADER()
        data_header.shareID = 0x103EA
        data_header.streamID = aardwolf.protocol.T128.share.STREAM_TYPE.MED
        data_header.pduType2 = aardwolf.protocol.T128.share.PDUTYPE2.SYNCHRONIZE

        client_synchronize_pdu = aardwolf.protocol.T128.synchronizepdu.TS_SYNCHRONIZE_PDU()
        client_synchronize_pdu.targetUser = self._RDPConnection__joined_channels["MCS"].channel_id

        security_header = None

        if self.cryptolayer is not None:
            security_header = aardwolf.protocol.T128.security.TS_SECURITY_HEADER()
            security_header.flags = aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT
            security_header.flagsHi = 0

        await self.handle_out_data(
            client_synchronize_pdu,
            security_header,
            data_header,
            None,
            self._RDPConnection__joined_channels["MCS"].channel_id,
            False)

        data_header = aardwolf.protocol.T128.inputeventpdu.TS_SHAREDATAHEADER()
        data_header.shareID = 0x103EA
        data_header.streamID = aardwolf.protocol.T128.share.STREAM_TYPE.MED
        data_header.pduType2 = aardwolf.protocol.T128.share.PDUTYPE2.CONTROL

        client_control_pdu = aardwolf.protocol.T128.controlpdu.TS_CONTROL_PDU()
        client_control_pdu.action = aardwolf.protocol.T128.controlpdu.CTRLACTION.COOPERATE
        client_control_pdu.grantId = 0
        client_control_pdu.controlId = 0

        security_header = None

        if self.cryptolayer is not None:
            security_header = aardwolf.protocol.T128.security.TS_SECURITY_HEADER()
            security_header.flags = aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT
            security_header.flagsHi = 0

        await self.handle_out_data(
            client_control_pdu,
            security_header,
            data_header,
            None,
            self._RDPConnection__joined_channels["MCS"].channel_id,
            False)

        data_header = aardwolf.protocol.T128.inputeventpdu.TS_SHAREDATAHEADER()
        data_header.shareID = 0x103EA
        data_header.streamID = aardwolf.protocol.T128.share.STREAM_TYPE.MED
        data_header.pduType2 = aardwolf.protocol.T128.share.PDUTYPE2.CONTROL

        client_control_pdu = aardwolf.protocol.T128.controlpdu.TS_CONTROL_PDU()
        client_control_pdu.action = aardwolf.protocol.T128.controlpdu.CTRLACTION.REQUEST_CONTROL
        client_control_pdu.grantId = 0
        client_control_pdu.controlId = 0

        security_header = None

        if self.cryptolayer is not None:
            security_header = aardwolf.protocol.T128.security.TS_SECURITY_HEADER()
            security_header.flags = aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT
            security_header.flagsHi = 0

        await self.handle_out_data(
            client_control_pdu,
            security_header,
            data_header,
            None,
            self._RDPConnection__joined_channels["MCS"].channel_id,
            False)

        data_header = aardwolf.protocol.T128.inputeventpdu.TS_SHAREDATAHEADER()
        data_header.shareID = 0x103EA
        data_header.streamID = aardwolf.protocol.T128.share.STREAM_TYPE.MED
        data_header.pduType2 = aardwolf.protocol.T128.share.PDUTYPE2.FONTLIST

        client_font_list_pdu = aardwolf.protocol.T128.fontlistpdu.TS_FONT_LIST_PDU()

        security_header = None

        if self.cryptolayer is not None:
            security_header = aardwolf.protocol.T128.security.TS_SECURITY_HEADER()
            security_header.flags = aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT
            security_header.flagsHi = 0

        await self.handle_out_data(
            client_font_list_pdu,
            security_header,
            data_header,
            None,
            self._RDPConnection__joined_channels["MCS"].channel_id,
            False)

    async def _RDPConnection__handle_mandatory_capability_exchange(self):
        """Handle capability exchange, skipping MONITOR_LAYOUT_PDU before synchronize."""

        exchange_ok, exchange_error =             await aardwolf.connection.RDPConnection._RDPConnection__handle_mandatory_capability_exchange(
                self)

        if exchange_error is None:
            return exchange_ok, exchange_error

        if "MONITOR_LAYOUT_PDU" not in str(exchange_error):
            return exchange_ok, exchange_error

        try:
            data_start_offset = self._get_capability_exchange_data_start_offset()

            await self._await_synchronize_after_confirm_active(data_start_offset)
            await self._finish_mandatory_capability_exchange_after_synchronize()

            return True, None

        except Exception as recovery_error:
            return None, recovery_error


    def _build_certificate_trust_metadata(self) -> dict:
        """Build metadata persisted alongside the server TLS certificate."""

        metadata = {
            "first_seen": datetime.datetime.now(datetime.UTC).isoformat(),
            "remote_ip": self.target.ip,
            "port": self.target.port,
        }

        if self.target.hostname is not None:
            metadata["hostname"] = self.target.hostname

        if self.target.domain is not None:
            metadata["domain"] = self.target.domain

        metadata["spn"] = self.target.to_target_string()

        return metadata

    async def credssp_auth(self):
        """Verify or accept the server TLS certificate before CredSSP authentication."""

        self._report_connection_progress(
            rdp_client.connection_progress.CONNECTION_STEP_VERIFYING_CERTIFICATE)

        transport_connection = self._RDPConnection__connection
        peer_certificate = transport_connection.get_peer_certificate()

        if peer_certificate is None:
            raise ValueError(
                "TLS peer certificate missing during CredSSP for {remote_ip}".format(
                    remote_ip=self.target.ip))

        remote_ip = self.target.ip
        if remote_ip is None:
            raise ValueError("remote IP missing on RDP target during certificate trust check")

        trust_metadata = self._build_certificate_trust_metadata()

        rdp_client.trust_store.verify_or_accept_server_certificate(
            remote_ip,
            peer_certificate,
            trust_metadata)

        self._report_connection_progress(
            rdp_client.connection_progress.CONNECTION_STEP_AUTHENTICATING)

        return await aardwolf.connection.RDPConnection.credssp_auth(self)



class RdpDesktopConnectionFactory(aardwolf.commons.factory.RDPConnectionFactory):
    """Factory that builds RdpDesktopConnection instead of the stock RDPConnection."""

    @staticmethod
    def from_url(connection_url, iosettings):
        """Build a desktop factory from an aardwolf connection URL."""

        import asyauth.common.credentials
        import aardwolf.commons.target

        target = aardwolf.commons.target.RDPTarget.from_url(connection_url)
        credential = asyauth.common.credentials.UniCredential.from_url(connection_url)

        return RdpDesktopConnectionFactory(
            iosettings,
            target,
            credential)


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
    import aardwolf.extensions.RDPECLIP.channel

    iosettings = aardwolf.commons.iosettings.RDPIOSettings()
    iosettings.channels = [
        aardwolf.extensions.RDPECLIP.channel.RDPECLIPChannel,
        RdpEdycChannel,
    ]
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
    """Forward fastpath bitmap updates without inferring resolution from tile size."""

    try:
        import aardwolf.protocol.fastpath
        import aardwolf.commons.queuedata.video

        if fpdu.fpOutputUpdates.updateCode == \
                aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.BITMAP:

            for bitmapdata in fpdu.fpOutputUpdates.update.rectangles:
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
