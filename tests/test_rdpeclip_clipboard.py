"""Unit tests for RDPECLIP clipboard monkey-patches."""

import unittest.mock

import aardwolf.extensions.RDPECLIP.protocol
import aardwolf.extensions.RDPECLIP.protocol.formatdatarequest
import aardwolf.extensions.RDPECLIP.protocol.formatlist

import rdp_pipe.rdp_connection


async def _run_empty_clipboard_format_data_request():
    """Invoke the patched handler when local clipboard data is unset."""

    channel = unittest.mock.Mock()
    channel.clipboard = unittest.mock.Mock()
    channel.clipboard.data = None
    channel.fragment_and_send = unittest.mock.AsyncMock()

    format_data_request = \
        aardwolf.extensions.RDPECLIP.protocol.formatdatarequest.CLIPRDR_FORMAT_DATA_REQUEST()
    format_data_request.requestedFormatId = \
        aardwolf.extensions.RDPECLIP.protocol.formatlist.CLIPBRD_FORMAT.CF_UNICODETEXT

    await rdp_pipe.rdp_connection._patched_rdpeclip_handle_format_data_request(
        channel,
        format_data_request)

    return channel


def test_empty_local_clipboard_answers_format_data_request_with_fail():
    """Server paste requests must not crash when clipboard.data is still None."""

    import asyncio

    channel = asyncio.run(_run_empty_clipboard_format_data_request())

    channel.fragment_and_send.assert_awaited_once()
    sent_message = channel.fragment_and_send.await_args.args[0]
    response_type = int.from_bytes(sent_message[0:2], byteorder="little", signed=False)
    response_flags = int.from_bytes(sent_message[2:4], byteorder="little", signed=False)

    assert response_type == \
        aardwolf.extensions.RDPECLIP.protocol.CB_TYPE.CB_FORMAT_DATA_RESPONSE.value
    assert response_flags == \
        aardwolf.extensions.RDPECLIP.protocol.CB_FLAG.CB_RESPONSE_FAIL.value


async def _run_matching_clipboard_format_data_request():
    """Invoke the patched handler when local clipboard holds the requested format."""

    channel = unittest.mock.Mock()
    channel.clipboard = unittest.mock.Mock()
    channel.clipboard.data = unittest.mock.Mock()
    channel.clipboard.data.datatype = \
        aardwolf.extensions.RDPECLIP.protocol.formatlist.CLIPBRD_FORMAT.CF_UNICODETEXT
    channel.clipboard.data.data = "hello"
    channel.fragment_and_send = unittest.mock.AsyncMock()

    format_data_request = \
        aardwolf.extensions.RDPECLIP.protocol.formatdatarequest.CLIPRDR_FORMAT_DATA_REQUEST()
    format_data_request.requestedFormatId = channel.clipboard.data.datatype

    with unittest.mock.patch.object(
            rdp_pipe.rdp_connection,
            "_ORIGINAL_RDPECLIP_HANDLE_FORMAT_DATA_REQUEST",
            unittest.mock.AsyncMock()) as original_handler:

        await rdp_pipe.rdp_connection._patched_rdpeclip_handle_format_data_request(
            channel,
            format_data_request)

        return original_handler


def test_nonempty_local_clipboard_delegates_to_aardwolf_handler():
    """When clipboard data exists, the stock aardwolf handler still runs."""

    import asyncio

    original_handler = asyncio.run(_run_matching_clipboard_format_data_request())

    original_handler.assert_awaited_once()
