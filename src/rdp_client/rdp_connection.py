"""RDPConnection subclass with RDPDISP-oriented capability flags and buffer resize."""

import asyncio
import copy
import datetime
import errno
import logging
import traceback

import aardwolf.commons.factory
import aardwolf.commons.iosettings
import aardwolf.commons.queuedata.video
import aardwolf.commons.target
import aardwolf.connection
import aardwolf.extensions.RDPECLIP.channel
import aardwolf.extensions.RDPEDYC.channel
import aardwolf.extensions.RDPEDYC.protocol
import aardwolf.extensions.RDPEDYC.protocol.create
import aardwolf.protocol.channelpdu
import aardwolf.protocol.fastpath
import aardwolf.protocol.T124.userdata.clientcoredata
import aardwolf.protocol.T124.userdata.constants
import aardwolf.protocol.T125.extendedinfopacket
import aardwolf.protocol.pdu.capabilities
import aardwolf.protocol.pdu.capabilities.bitmap
import aardwolf.protocol.pdu.capabilities.brush
import aardwolf.protocol.pdu.capabilities.bitmapcache
import aardwolf.protocol.pdu.capabilities.general
import aardwolf.protocol.pdu.capabilities.glyph
import aardwolf.protocol.pdu.capabilities.input
import aardwolf.protocol.pdu.capabilities.largepointer
import aardwolf.protocol.pdu.capabilities.offscreen
import aardwolf.protocol.pdu.capabilities.order
import aardwolf.protocol.pdu.capabilities.pointer
import aardwolf.protocol.pdu.capabilities.sound
import aardwolf.protocol.pdu.capabilities.virtualchannel
import aardwolf.protocol.T128.clientconfirmactivepdu
import aardwolf.protocol.T128.controlpdu
import aardwolf.protocol.T128.fontlistpdu
import aardwolf.protocol.T128.inputeventpdu
import aardwolf.protocol.T128.security
import aardwolf.protocol.T128.serverdemandactivepdu
import aardwolf.protocol.T128.seterrorinfopdu
import aardwolf.protocol.T128.share
import aardwolf.protocol.T128.synchronizepdu
import aardwolf.vncconnection
import asyauth.common.credentials
import PIL.Image

import rdp_client.connection_progress
import rdp_client.display_control
import rdp_client.pointer_debug
import rdp_client.pointer_update
import rdp_client.trust_store


_LOGGER = logging.getLogger(__name__)
_AARDWOLF_LOGGER = logging.getLogger("aardwolf")
DISPLAY_CONTROL_CAPS_TIMEOUT_SECONDS = 10.0
TERMINATE_DISCONNECT_TIMEOUT_SECONDS = 2.0

_CONNECTING_DESKTOP_CONNECTION = None
_ORIGINAL_TS_UD_CS_CORE_TO_BYTES = \
    aardwolf.protocol.T124.userdata.clientcoredata.TS_UD_CS_CORE.to_bytes
_ORIGINAL_POINTER_CAPABILITYSET_INIT = \
    aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET.__init__


def _patched_ts_ud_cs_core_to_bytes(self):
    """Augment early capability flags while the desktop connection is negotiating."""

    global _CONNECTING_DESKTOP_CONNECTION

    if _CONNECTING_DESKTOP_CONNECTION is not None:
        if self.earlyCapabilityFlags is not None:
            self.earlyCapabilityFlags = (
                self.earlyCapabilityFlags
                | aardwolf.protocol.T124.userdata.constants.RNS_UD_CS.SUPPORT_MONITOR_LAYOUT_PDU)

            if _CONNECTING_DESKTOP_CONNECTION.iosettings.video_bpp_max == 32:
                self.earlyCapabilityFlags = (
                    self.earlyCapabilityFlags
                    | aardwolf.protocol.T124.userdata.constants.RNS_UD_CS.WANT_32BPP_SESSION)
                self.highColorDepth = \
                    aardwolf.protocol.T124.userdata.constants.HIGH_COLOR_DEPTH.HIGH_COLOR_24BPP

    return _ORIGINAL_TS_UD_CS_CORE_TO_BYTES(self)


aardwolf.protocol.T124.userdata.clientcoredata.TS_UD_CS_CORE.to_bytes = \
    _patched_ts_ud_cs_core_to_bytes


def _patched_pointer_capabilityset_init(self):
    """Advertise color pointer support during capability exchange."""

    _ORIGINAL_POINTER_CAPABILITYSET_INIT(self)
    self.colorPointerFlag = True
    self.colorPointerCacheSize = 25
    self.pointerCacheSize = 25


aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET.__init__ = \
    _patched_pointer_capabilityset_init

_ORIGINAL_HANDLE_OUT_DATA = aardwolf.connection.RDPConnection.handle_out_data


def _augment_client_confirm_active_capabilities(confirm_active_pdu):
    """Add pointer/input capabilities mstsc sends but aardwolf omits."""

    if not isinstance(confirm_active_pdu, aardwolf.protocol.T128.clientconfirmactivepdu.TS_CONFIRM_ACTIVE_PDU):
        return

    pointer_capability_present = False

    for capability_set in confirm_active_pdu.capabilitySets:
        if capability_set.capabilitySetType == aardwolf.protocol.pdu.capabilities.CAPSTYPE.POINTER:
            pointer_capability_present = True

        if capability_set.capabilitySetType == aardwolf.protocol.pdu.capabilities.CAPSTYPE.BITMAP:
            capability_set.capability.desktopResizeFlag = True

        if capability_set.capabilitySetType == aardwolf.protocol.pdu.capabilities.CAPSTYPE.INPUT:
            input_capability = capability_set.capability
            input_capability.inputFlags = (
                input_capability.inputFlags
                | aardwolf.protocol.pdu.capabilities.input.INPUT_FLAG.UNICODE
                | aardwolf.protocol.pdu.capabilities.input.INPUT_FLAG.MOUSE_HWHEEL)

    if pointer_capability_present:
        large_pointer_capability_present = False

        for capability_set in confirm_active_pdu.capabilitySets:
            if capability_set.capabilitySetType == \
                    aardwolf.protocol.pdu.capabilities.CAPSTYPE.LARGE_POINTER:
                large_pointer_capability_present = True

        if large_pointer_capability_present is False:
            large_pointer_capability = \
                aardwolf.protocol.pdu.capabilities.largepointer.TS_LARGE_POINTER_CAPABILITYSET()
            large_pointer_capability.largePointerSupportFlags = \
                aardwolf.protocol.pdu.capabilities.largepointer.LARGE_POINTER.FLAG_96x96

            confirm_active_pdu.capabilitySets.append(
                aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(
                    large_pointer_capability))


async def _patched_handle_out_data(
        self,
        dataobj,
        sec_hdr,
        datacontrol_hdr,
        sharecontrol_hdr,
        channel_id,
        is_fastpath):

    _augment_client_confirm_active_capabilities(dataobj)

    return await _ORIGINAL_HANDLE_OUT_DATA(
        self,
        dataobj,
        sec_hdr,
        datacontrol_hdr,
        sharecontrol_hdr,
        channel_id,
        is_fastpath)


aardwolf.connection.RDPConnection.handle_out_data = _patched_handle_out_data


def _can_request_graceful_rdp_shutdown(connection) -> bool:
    """Return True when the MCS shutdown PDU can be sent on a joined session."""

    joined_channels = getattr(connection, "_RDPConnection__joined_channels", None)

    if joined_channels is None:
        return False

    try:
        joined_channels["MCS"]
    except KeyError:
        return False

    server_connect_pdu = getattr(connection, "_RDPConnection__server_connect_pdu", None)

    if server_connect_pdu is None:
        return False

    transport_connection = getattr(connection, "_RDPConnection__connection", None)

    if transport_connection is None:
        return False

    return True


def _is_expected_shutdown_failure(error: BaseException) -> bool:
    """Return True when send_disconnect failed because the transport is already gone."""

    if isinstance(error, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
        return True

    if isinstance(error, OSError):

        if error.errno in (
                errno.ECONNRESET,
                errno.EPIPE,
                errno.ECONNABORTED,
                errno.ENOTCONN,
                errno.ETIMEDOUT):
            return True

    if isinstance(error, KeyError):
        return True

    return False


async def _patched_aardwolf_terminate(self):
    """Skip or silence graceful shutdown when the server or transport is already gone."""

    try:

        if getattr(self, "_RDPConnection__terminate_called", False) is True:
            return True, None

        self._RDPConnection__terminate_called = True

        if _can_request_graceful_rdp_shutdown(self):

            will_shutdown, shutdown_error = await self.send_disconnect()

            if shutdown_error is not None:

                if _is_expected_shutdown_failure(shutdown_error) is False:
                    _AARDWOLF_LOGGER.warning("Error while requesting shutdown")

            elif will_shutdown is False:
                _AARDWOLF_LOGGER.warning(
                    "Server refused to shutdown, proceeding with termination anyway...")

        joined_channels = self._RDPConnection__joined_channels

        for channel_name in joined_channels:
            await joined_channels[channel_name].disconnect()

        if self.ext_out_queue is not None:
            await self.ext_out_queue.put(None)

        external_reader_task = getattr(self, "_RDPConnection__external_reader_task", None)

        if external_reader_task is not None:
            external_reader_task.cancel()

        x224_reader_task = getattr(self, "_RDPConnection__x224_reader_task", None)

        if x224_reader_task is not None:
            x224_reader_task.cancel()

        return True, None

    except Exception as error:
        _AARDWOLF_LOGGER.error(
            "Error: {error}, {traceback_text}".format(
                error=error,
                traceback_text=traceback.format_exc()))

        return None, error

    finally:
        self.disconnected_evt.set()

        transport_connection = getattr(self, "_RDPConnection__connection", None)

        if transport_connection is not None:
            await transport_connection.close()


aardwolf.connection.RDPConnection.terminate = _patched_aardwolf_terminate

_ORIGINAL_RDPECLIP_HANDLE_FORMAT_DATA_REQUEST = \
    aardwolf.extensions.RDPECLIP.channel.RDPECLIPChannel._handle_format_data_request


async def _patched_rdpeclip_handle_format_data_request(self, format_data_request):
    """Reply CB_RESPONSE_FAIL when the server requests clipboard data we do not hold."""

    clipboard_data = self.clipboard.data

    if clipboard_data is None:
        _LOGGER.debug(
            "RDPECLIP CB_FORMAT_DATA_REQUEST for format {format_id} with empty local clipboard".format(
                format_id=format_data_request.requestedFormatId))

        fail_response_message = \
            aardwolf.extensions.RDPECLIP.protocol.CLIPRDR_HEADER.serialize_packet(
                aardwolf.extensions.RDPECLIP.protocol.CB_TYPE.CB_FORMAT_DATA_RESPONSE,
                aardwolf.extensions.RDPECLIP.protocol.CB_FLAG.CB_RESPONSE_FAIL,
                None)

        await self.fragment_and_send(fail_response_message)

        return

    return await _ORIGINAL_RDPECLIP_HANDLE_FORMAT_DATA_REQUEST(self, format_data_request)


aardwolf.extensions.RDPECLIP.channel.RDPECLIPChannel._handle_format_data_request = \
    _patched_rdpeclip_handle_format_data_request


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
        self._pointer_cache = rdp_client.pointer_update.RdpPointerCache()
        self._pointer_update_listener = None
        self._pointer_pdu_count_by_update_code: dict[int, int] = {}
        self._share_channel_task = None
        self._terminate_in_progress = False

    def set_pointer_update_listener(self, listener):
        """Register a callback invoked immediately for each pointer PDU."""

        self._pointer_update_listener = listener

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

    async def terminate(self):
        """Cancel share-channel reactivation handling, then disconnect."""

        # aardwolf __x224_reader finally calls terminate() while that reader task
        # is still current; the outer terminate() will drain reader tasks afterward.

        if getattr(self, "_terminate_in_progress", False):
            return True, None

        self._terminate_in_progress = True
        terminate_result = True, None

        try:

            # Stop draining MCS before send_disconnect waits on the same queue.

            share_channel_task = self._share_channel_task
            if share_channel_task is not None:

                self._share_channel_task = None
                share_channel_task.cancel()

                try:
                    await share_channel_task

                except asyncio.CancelledError:
                    pass

            # Bound send_disconnect so a mid-connect MCS wait cannot stall past
            # the GUI shutdown join.

            try:
                aardwolf_terminate = aardwolf.connection.RDPConnection.terminate(self)
                terminate_result = \
                    await asyncio.wait_for(
                        aardwolf_terminate,
                        timeout=TERMINATE_DISCONNECT_TIMEOUT_SECONDS)

            except asyncio.TimeoutError:

                terminate_result = (None, None)
                await self._close_aardwolf_transport()

            await self._await_cancelled_aardwolf_reader_tasks()

            return terminate_result

        finally:
            await self._signal_disconnect_to_session_loops()
            self._terminate_in_progress = False

    async def _signal_disconnect_to_session_loops(self):
        """Unblock run_until_stopped when aardwolf terminate wedges on send_disconnect."""

        # aardwolf terminate only puts None after send_disconnect returns; a dead socket
        # leaves MCS.out_queue.get() waiting and run_until_stopped never sees disconnect.

        disconnected_event = getattr(self, "disconnected_evt", None)

        if disconnected_event is not None:
            disconnected_event.set()

        output_queue = getattr(self, "ext_out_queue", None)

        if output_queue is not None:
            await output_queue.put(None)

    async def _close_aardwolf_transport(self):
        """Close the aardwolf transport if terminate() timed out mid-disconnect."""

        # __new__ test shells and mid-connect failures may have no transport.

        transport_connection = getattr(
            self,
            "_RDPConnection__connection",
            None)

        if transport_connection is None:
            return

        await transport_connection.close()

    async def _await_cancelled_aardwolf_reader_tasks(self):
        """Await aardwolf x224 and external readers after they are cancelled."""

        reader_tasks = [
            getattr(self, "_RDPConnection__x224_reader_task", None),
            getattr(self, "_RDPConnection__external_reader_task", None),
        ]

        # aardwolf cancel()s these tasks but does not await them.

        current_task = asyncio.current_task()

        for reader_task in reader_tasks:

            if reader_task is None:
                continue

            if reader_task is current_task:
                continue

            if reader_task.done():
                self._consume_reader_task_outcome(reader_task)

                continue

            reader_task.cancel()

            try:
                await reader_task

            except asyncio.CancelledError:
                pass

            except Exception:
                pass

    def _consume_reader_task_outcome(self, reader_task: asyncio.Task):
        """Retrieve a finished reader task result without awaiting the current task."""

        if reader_task.cancelled():
            return

        reader_task.exception()

    async def connect(self):
        """Connect while capability-flag patching is active for Client Core Data."""

        global _CONNECTING_DESKTOP_CONNECTION

        _CONNECTING_DESKTOP_CONNECTION = self

        try:

            self._report_connection_progress(
                rdp_client.connection_progress.CONNECTION_STEP_CONNECTING)

            connect_result = await aardwolf.connection.RDPConnection.connect(self)

            if connect_result is not None and connect_result[1] is None:

                # Demand Active after RDPDISP layout sits on MCS.out_queue until we drain it.

                self._share_channel_task = asyncio.create_task(
                    self._run_share_channel_loop())

            return connect_result

        finally:
            _CONNECTING_DESKTOP_CONNECTION = None


    def _get_capability_exchange_data_start_offset(self) -> int:
        """Return the MCS payload offset when server encryption level is 1."""

        data_start_offset = 0

        if self._RDPConnection__server_connect_pdu[
                aardwolf.protocol.T124.userdata.constants.TS_UD_TYPE.SC_SECURITY].encryptionLevel == 1:
            data_start_offset = 4

        return data_start_offset

    async def _await_synchronize_after_confirm_active(self, data_start_offset: int):
        """Read MCS replies until SYNCHRONIZE, skipping leftover share data PDUs."""

        # Skip Deactivate All and non-error data PDUs until the server Synchronize arrives.

        while True:

            data, err = await self._RDPConnection__joined_channels["MCS"].out_queue.get()

            if err is not None:
                raise err

            data = data[data_start_offset:]
            share_control_header = \
                aardwolf.protocol.T128.share.TS_SHARECONTROLHEADER.from_bytes(data)

            if share_control_header.pduType != aardwolf.protocol.T128.share.PDUTYPE.DATAPDU:
                continue

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

    async def _finish_mandatory_capability_exchange_after_synchronize(self):
        """Send client synchronize, control, and font-list PDUs after server synchronize."""

        # Replay the post-Confirm-Active handshake aardwolf uses at connect.

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

    async def _run_share_channel_loop(self):
        """Drain MCS share PDUs so Deactivate All / Demand Active are answered."""

        # Read every MCS share PDU; only Demand Active starts reactivation.

        mcs_channel = self._RDPConnection__joined_channels["MCS"]
        data_start_offset = self._get_capability_exchange_data_start_offset()

        try:

            while True:

                queue_item = await mcs_channel.out_queue.get()
                data = queue_item[0]
                queue_error = queue_item[1]

                if queue_error is not None:

                    _LOGGER.error(
                        "MCS share channel error: {error}".format(error=queue_error))

                    return

                # Skip leftover Font Map / Control PDUs from the original connect.

                payload = data[data_start_offset:]
                share_control_header = \
                    aardwolf.protocol.T128.share.TS_SHARECONTROLHEADER.from_bytes(payload)

                if share_control_header.pduType != \
                        aardwolf.protocol.T128.share.PDUTYPE.DEMANDACTIVEPDU:

                    continue

                try:
                    await self._complete_deactivation_reactivation(payload)

                except Exception as reactivation_error:

                    _LOGGER.error(
                        "RDP deactivation-reactivation failed: {error}".format(
                            error=reactivation_error))

        except asyncio.CancelledError:
            return

    async def _complete_deactivation_reactivation(self, demand_active_payload: bytes):
        """Answer a mid-session Demand Active after RDPDISP changes desktop size."""

        # Parse Demand Active, resize the local buffer, and Confirm Active.

        demand_active = \
            aardwolf.protocol.T128.serverdemandactivepdu.TS_DEMAND_ACTIVE_PDU.from_bytes(
                demand_active_payload)

        self._apply_demand_active_desktop_size(demand_active)
        await self._send_client_confirm_active()

        # Repeat Synchronize / Control / Font List, then reopen RDPDISP if it was dropped.

        data_start_offset = self._get_capability_exchange_data_start_offset()

        await self._await_synchronize_after_confirm_active(data_start_offset)
        await self._finish_mandatory_capability_exchange_after_synchronize()
        await self.open_display_control_channel()

        if self.display_control_channel is None:
            return

        if self.display_control_channel.caps_received:
            return

        await self.display_control_channel.wait_for_caps(
            DISPLAY_CONTROL_CAPS_TIMEOUT_SECONDS)

    def _apply_demand_active_desktop_size(self, demand_active):
        """Resize the local framebuffer to the desktop size in Demand Active."""

        # Use the BITMAP capability desktop size from this Demand Active PDU.

        for capability_set in demand_active.capabilitySets:
            if capability_set.capabilitySetType != aardwolf.protocol.pdu.capabilities.CAPSTYPE.BITMAP:
                continue

            bitmap_capability = capability_set.capability
            desktop_width = bitmap_capability.desktopWidth
            desktop_height = bitmap_capability.desktopHeight

            if desktop_width == self.iosettings.video_width \
                    and desktop_height == self.iosettings.video_height:

                return

            self.reallocate_desktop_buffer(desktop_width, desktop_height)

            return

    async def _send_client_confirm_active(self):
        """Send Confirm Active using the current iosettings desktop size."""

        # Match aardwolf connect caps, but advertise desktopResizeFlag for later layouts.

        capability_sets = []

        general_capability = aardwolf.protocol.pdu.capabilities.general.TS_GENERAL_CAPABILITYSET()
        general_capability.osMajorType = \
            aardwolf.protocol.pdu.capabilities.general.OSMAJORTYPE.WINDOWS
        general_capability.osMinorType = \
            aardwolf.protocol.pdu.capabilities.general.OSMINORTYPE.WINDOWS_NT
        general_capability.extraFlags = (
            aardwolf.protocol.pdu.capabilities.general.EXTRAFLAG.FASTPATH_OUTPUT_SUPPORTED
            | aardwolf.protocol.pdu.capabilities.general.EXTRAFLAG.NO_BITMAP_COMPRESSION_HDR
            | aardwolf.protocol.pdu.capabilities.general.EXTRAFLAG.LONG_CREDENTIALS_SUPPORTED)

        if self.cryptolayer is not None and self.cryptolayer.use_encrypted_mac is True:
            general_capability.extraFlags = (
                general_capability.extraFlags
                | aardwolf.protocol.pdu.capabilities.general.EXTRAFLAG.ENC_SALTED_CHECKSUM)

        capability_sets.append(general_capability)

        bitmap_capability = aardwolf.protocol.pdu.capabilities.bitmap.TS_BITMAP_CAPABILITYSET()
        bitmap_capability.preferredBitsPerPixel = self.iosettings.video_bpp_max
        bitmap_capability.desktopWidth = self.iosettings.video_width
        bitmap_capability.desktopHeight = self.iosettings.video_height
        bitmap_capability.desktopResizeFlag = True
        capability_sets.append(bitmap_capability)

        order_capability = aardwolf.protocol.pdu.capabilities.order.TS_ORDER_CAPABILITYSET()
        order_capability.orderFlags = (
            aardwolf.protocol.pdu.capabilities.order.ORDERFLAG.ZEROBOUNDSDELTASSUPPORT
            | aardwolf.protocol.pdu.capabilities.order.ORDERFLAG.NEGOTIATEORDERSUPPORT
            | aardwolf.protocol.pdu.capabilities.order.ORDERFLAG.SOLIDPATTERNBRUSHONLY)
        capability_sets.append(order_capability)

        capability_sets.append(aardwolf.protocol.pdu.capabilities.bitmapcache.TS_BITMAPCACHE_CAPABILITYSET())
        capability_sets.append(aardwolf.protocol.pdu.capabilities.pointer.TS_POINTER_CAPABILITYSET())

        input_capability = aardwolf.protocol.pdu.capabilities.input.TS_INPUT_CAPABILITYSET()
        input_capability.inputFlags = aardwolf.protocol.pdu.capabilities.input.INPUT_FLAG.SCANCODES
        input_capability.keyboardLayout = self.iosettings.keyboard_layout
        input_capability.keyboardType = self.iosettings.keyboard_type
        input_capability.keyboardSubType = self.iosettings.keyboard_subtype
        input_capability.keyboardFunctionKey = self.iosettings.keyboard_functionkey
        capability_sets.append(input_capability)

        capability_sets.append(aardwolf.protocol.pdu.capabilities.brush.TS_BRUSH_CAPABILITYSET())
        capability_sets.append(aardwolf.protocol.pdu.capabilities.glyph.TS_GLYPHCACHE_CAPABILITYSET())
        capability_sets.append(aardwolf.protocol.pdu.capabilities.offscreen.TS_OFFSCREEN_CAPABILITYSET())

        virtual_channel_capability = \
            aardwolf.protocol.pdu.capabilities.virtualchannel.TS_VIRTUALCHANNEL_CAPABILITYSET()
        virtual_channel_capability.flags = (
            aardwolf.protocol.pdu.capabilities.virtualchannel.VCCAPS.COMPR_CS_8K
            | aardwolf.protocol.pdu.capabilities.virtualchannel.VCCAPS.COMPR_SC)
        capability_sets.append(virtual_channel_capability)
        capability_sets.append(aardwolf.protocol.pdu.capabilities.sound.TS_SOUND_CAPABILITYSET())

        share_header = aardwolf.protocol.T128.share.TS_SHARECONTROLHEADER()
        share_header.pduType = aardwolf.protocol.T128.share.PDUTYPE.CONFIRMACTIVEPDU
        share_header.pduVersion = 1
        share_header.pduSource = self._RDPConnection__joined_channels["MCS"].channel_id

        confirm_active_pdu = aardwolf.protocol.T128.clientconfirmactivepdu.TS_CONFIRM_ACTIVE_PDU()
        confirm_active_pdu.shareID = 0x103EA
        confirm_active_pdu.originatorID = 1002

        for capability in capability_sets:
            confirm_active_pdu.capabilitySets.append(
                aardwolf.protocol.pdu.capabilities.TS_CAPS_SET.from_capability(capability))

        security_header = None

        if self.cryptolayer is not None:
            security_header = aardwolf.protocol.T128.security.TS_SECURITY_HEADER()
            security_header.flags = aardwolf.protocol.T128.security.SEC_HDR_FLAG.ENCRYPT
            security_header.flagsHi = 0

        await self.handle_out_data(
            confirm_active_pdu,
            security_header,
            None,
            share_header,
            self._RDPConnection__joined_channels["MCS"].channel_id,
            False)

    async def _RDPConnection__handle_mandatory_capability_exchange(self):
        """Handle capability exchange, skipping MONITOR_LAYOUT_PDU before synchronize."""

        # aardwolf raises if MONITOR_LAYOUT arrives before Synchronize; skip it and continue.

        exchange_ok, exchange_error = \
            await aardwolf.connection.RDPConnection._RDPConnection__handle_mandatory_capability_exchange(
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

        target = aardwolf.commons.target.RDPTarget.from_url(connection_url)
        credential = asyauth.common.credentials.UniCredential.from_url(connection_url)

        return RdpDesktopConnectionFactory(
            iosettings,
            target,
            credential)


    def get_connection(self, iosettings):
        """Return a desktop connection using copied target and credential."""

        copied_iosettings = copy.deepcopy(iosettings)
        copied_iosettings.vchannels = iosettings.vchannels
        credential = self.get_credential()
        target = self.get_target()

        if target.dialect is not None:

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
        color_depth: int = 32,
        resolution_request_callback=None) -> "aardwolf.commons.iosettings.RDPIOSettings":
    """Create iosettings with RDPDISP channel registration and the requested bpp."""

    iosettings = aardwolf.commons.iosettings.RDPIOSettings()
    iosettings.channels = [
        aardwolf.extensions.RDPECLIP.channel.RDPECLIPChannel,
        RdpEdycChannel,
    ]
    iosettings.video_width = video_width
    iosettings.video_height = video_height
    iosettings.video_bpp_max = color_depth

    # aardwolf maps only 4/8/15/16/24 into TS_UD_CS_CORE.colorDepth; 32-bpp sessions
    # use 24 on the wire plus WANT_32BPP_SESSION from _patched_ts_ud_cs_core_to_bytes.
    wire_color_depth = color_depth
    if color_depth == 32:
        wire_color_depth = 24

    iosettings.video_bpp_min = wire_color_depth
    iosettings.clipboard_use_pyperclip = False
    iosettings.performance_flags = (
        iosettings.performance_flags
        & ~aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_WALLPAPER
        & ~aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_CURSORSETTINGS
        | aardwolf.protocol.T125.extendedinfopacket.PERF.DISABLE_CURSOR_SHADOW)

    display_channel = rdp_client.display_control.DisplayControlChannel(
        resolution_request_callback=resolution_request_callback)

    iosettings.vchannels[
        rdp_client.display_control.DISPLAY_CONTROL_CHANNEL_NAME] = display_channel

    return iosettings, display_channel


async def _process_pointer_fastpath_update(
        connection: RdpDesktopConnection,
        fastpath_update) -> rdp_client.pointer_update.RdpPointerUpdate | None:
    """Translate a fast-path pointer update PDU into an RdpPointerUpdate."""

    update_code = fastpath_update.updateCode

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.PTR_DEFAULT:
        return rdp_client.pointer_update.RdpPointerUpdate.build_default()

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.PTR_NULL:
        return rdp_client.pointer_update.RdpPointerUpdate.build_hidden()

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.PTR_POSITION:
        return None

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.COLOR:
        color_pointer_attribute = fastpath_update.update

        return rdp_client.pointer_update.build_bitmap_pointer_update_from_color_attribute(
            color_pointer_attribute,
            24,
            connection._pointer_cache,
            fastpath_update.updateData)

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.POINTER:
        pointer_attribute = fastpath_update.update
        color_update_data = fastpath_update.updateData

        if color_update_data is not None and len(color_update_data) > 2:
            color_update_data = color_update_data[2:]

        return rdp_client.pointer_update.build_bitmap_pointer_update_from_color_attribute(
            pointer_attribute.colorPtrAttr,
            pointer_attribute.xorBpp,
            connection._pointer_cache,
            color_update_data)

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.LARGE_POINTER:
        large_pointer_attribute = fastpath_update.update

        return rdp_client.pointer_update.build_bitmap_pointer_update_from_large_attribute(
            large_pointer_attribute,
            connection._pointer_cache,
            fastpath_update.updateData)

    if update_code == aardwolf.protocol.fastpath.FASTPATH_UPDATETYPE.CACHED:
        cached_pointer_attribute = fastpath_update.update
        cache_index = cached_pointer_attribute.cachedPointerUpdateData
        cached_pointer_update = connection._pointer_cache.lookup_bitmap(cache_index)

        if cached_pointer_update is None:
            _LOGGER.warning(
                "pointer cache miss for CACHED index {cache_index}".format(
                    cache_index=cache_index))
            rdp_client.pointer_debug.write_pointer_debug(
                "pointer pdu: CACHED cache miss index={cache_index}".format(
                    cache_index=cache_index))

        return cached_pointer_update

    return None


async def _rdp_desktop_process_fastpath(self, fpdu):
    """Forward fastpath bitmap and pointer updates to the output queue."""

    try:
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

        else:
            update_code = int(fpdu.fpOutputUpdates.updateCode)
            pointer_pdu_count = self._pointer_pdu_count_by_update_code.get(update_code, 0)
            self._pointer_pdu_count_by_update_code[update_code] = pointer_pdu_count + 1

            pointer_update = await _process_pointer_fastpath_update(self, fpdu.fpOutputUpdates)

            if pointer_update is not None:
                debug_detail = "kind={kind}".format(kind=pointer_update.kind.value)

                if pointer_update.kind == rdp_client.pointer_update.RdpPointerUpdateKind.BITMAP:
                    debug_detail = (
                        "kind=bitmap xor_bpp={xor_bpp} cache_index={cache_index} size={width}x{height}".format(
                            xor_bpp=pointer_update.xor_bits_per_pixel,
                            cache_index=pointer_update.cache_index,
                            width=pointer_update.image.width if pointer_update.image is not None else 0,
                            height=pointer_update.image.height if pointer_update.image is not None else 0))

                rdp_client.pointer_debug.write_pointer_debug(
                    "pointer pdu: {update_code} {debug_detail}".format(
                        update_code=fpdu.fpOutputUpdates.updateCode,
                        debug_detail=debug_detail))

                await self.ext_out_queue.put(pointer_update)

    except Exception as error:
        _LOGGER.error(
            "fastpath processing failed: {error}".format(error=error))
        rdp_client.pointer_debug.write_pointer_debug(
            "pointer pdu: fastpath error {error}".format(error=error))


RdpDesktopConnection._RDPConnection__process_fastpath = _rdp_desktop_process_fastpath
