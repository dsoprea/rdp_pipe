"""Integration tests for RdpAsyncSession using MockRdpConnection."""

import asyncio
import base64
import io
import types

import aardwolf.commons.queuedata
import aardwolf.commons.queuedata.clipboard
import aardwolf.commons.queuedata.video
import PIL.Image
import pytest

import rdp_client.connection_progress
import rdp_client.pointer_update
import rdp_client.rdp_connection
import rdp_client.rdp_session_core

import tests.support.mock_rdp_connection


CONNECTION_URL = "rdp+ntlm-password://user:pass@10.0.0.5"


def _patch_factory_from_url(monkeypatch, mock_connection):
    """Monkeypatch RdpDesktopConnectionFactory.from_url to return the mock."""

    def fake_from_url(connection_url, iosettings):
        stub_factory = types.SimpleNamespace()
        stub_factory.get_connection = \
            lambda copied_iosettings: mock_connection.bind_iosettings(copied_iosettings)

        return stub_factory

    monkeypatch.setattr(
        rdp_client.rdp_connection.RdpDesktopConnectionFactory,
        "from_url",
        staticmethod(fake_from_url))


async def test_connect_reports_ready_progress(connected_session):
    """connect() completes with RDPDISP caps and marks the session connected."""

    assert connected_session.is_connected is True
    assert connected_session.display_caps_unavailable is False
    assert connected_session.event_loop is not None


async def test_connect_without_caps_marks_display_unavailable(monkeypatch):
    """When the mock skips caps, seamless resize is disabled."""

    mock_connection = tests.support.mock_rdp_connection.MockRdpConnection(
        1280,
        800,
        deliver_caps=False)

    _patch_factory_from_url(monkeypatch, mock_connection)

    session = rdp_client.rdp_session_core.RdpAsyncSession(
        CONNECTION_URL,
        1280,
        800)

    progress_steps = []
    session.set_progress_callback(progress_steps.append)

    await session.connect()

    assert session.is_connected is True
    assert session.display_caps_unavailable is True
    assert progress_steps[-1] == rdp_client.connection_progress.CONNECTION_STEP_READY


async def test_drain_queued_pointer_updates_dispatches_before_video(connected_session):
    """Pointer updates are drained without dropping queued video rectangles."""

    pointer_updates = []
    connected_session.add_pointer_update_callback(pointer_updates.append)

    video_rectangle = aardwolf.commons.queuedata.video.RDP_VIDEO()
    video_rectangle.x = 0
    video_rectangle.y = 0
    video_rectangle.width = 4
    video_rectangle.height = 4
    video_rectangle.data = PIL.Image.new("RGBA", (4, 4))

    pointer_update = rdp_client.pointer_update.RdpPointerUpdate.build_default()

    await connected_session.connection.ext_out_queue.put(pointer_update)
    await connected_session.connection.ext_out_queue.put(video_rectangle)

    await connected_session.drain_queued_pointer_updates()

    assert len(pointer_updates) == 1
    assert pointer_updates[0].kind == rdp_client.pointer_update.RdpPointerUpdateKind.DEFAULT

    requeued_item = await asyncio.wait_for(
        connected_session.connection.ext_out_queue.get(),
        timeout=1.0)

    assert requeued_item is video_rectangle


async def test_handle_receive_geometry_returns_session_dimensions(connected_session):
    """receive_geometry reports iosettings width, height, and color depth."""

    result = await connected_session.handle_receive_geometry()

    assert result == {
        "width": 1280,
        "height": 800,
        "color_depth": 32,
    }


async def test_handle_send_geometry_requests_resolution(connected_session):
    """send_geometry forwards clamped dimensions through the display channel."""

    result = await connected_session.handle_send_geometry(1921, 900)

    assert result == {"width": 1920, "height": 900}


async def test_handle_receive_screenshot_returns_png(connected_session):
    """receive_screenshot encodes the mock desktop buffer as base64 PNG."""

    result = await connected_session.handle_receive_screenshot("png", 9)

    image_bytes = base64.standard_b64decode(result["data"])
    screenshot_image = PIL.Image.open(io.BytesIO(image_bytes))

    assert result["width"] == 1280
    assert result["height"] == 800
    assert result["format"] == "png"
    assert screenshot_image.size == (1280, 800)


async def test_handle_receive_screenshot_fails_without_buffer_data(monkeypatch):
    """Empty framebuffer surfaces as RdpSessionError."""

    mock_connection = tests.support.mock_rdp_connection.MockRdpConnection(
        1280,
        800,
        desktop_buffer_has_data=False)

    _patch_factory_from_url(monkeypatch, mock_connection)

    session = rdp_client.rdp_session_core.RdpAsyncSession(
        CONNECTION_URL,
        1280,
        800)

    await session.connect()

    with pytest.raises(rdp_client.rdp_session_core.RdpSessionError):
        await session.handle_receive_screenshot()


async def test_handle_send_click_enqueues_mouse_messages(connected_session):
    """send_click puts press and release messages on ext_in_queue."""

    await connected_session.handle_send_click(100, 200, "left")

    first_message = await asyncio.wait_for(
        connected_session.connection.ext_in_queue.get(),
        timeout=1.0)
    second_message = await asyncio.wait_for(
        connected_session.connection.ext_in_queue.get(),
        timeout=1.0)

    assert first_message.type == aardwolf.commons.queuedata.RDPDATATYPE.MOUSE
    assert second_message.type == aardwolf.commons.queuedata.RDPDATATYPE.MOUSE


async def test_handle_send_key_enqueues_keyboard_messages(connected_session):
    """send_key puts unicode keyboard messages on ext_in_queue."""

    await connected_session.handle_send_key(keys="a")

    first_message = await asyncio.wait_for(
        connected_session.connection.ext_in_queue.get(),
        timeout=1.0)

    assert first_message.type == aardwolf.commons.queuedata.RDPDATATYPE.KEYUNICODE


async def test_run_until_stopped_exits_when_stop_event_set_without_queue_items(
        connected_session):
    """stop() must unblock run_until_stopped even when ext_out_queue is empty."""

    drain_task = asyncio.create_task(connected_session.run_until_stopped())

    await asyncio.sleep(0.05)

    stop_task = asyncio.create_task(connected_session.stop())

    await asyncio.wait_for(
        asyncio.gather(drain_task, stop_task),
        timeout=2.0)


async def test_push_local_clipboard_text_forwards_to_connection(connected_session):
    """push_local_clipboard_text advertises text on the RDPECLIP channel."""

    await connected_session.push_local_clipboard_text("hello from local")

    assert connected_session.connection.clipboard_text_pushes == ["hello from local"]


async def test_run_until_stopped_emits_clipboard_text(connected_session):
    """CLIPBOARD_DATA_TXT queue items invoke registered clipboard callbacks."""

    clipboard_texts = []
    connected_session.add_clipboard_text_callback(clipboard_texts.append)

    clipboard_data = aardwolf.commons.queuedata.clipboard.RDP_CLIPBOARD_DATA_TXT(
        data="hello from remote")

    drain_task = asyncio.create_task(connected_session.run_until_stopped())

    await connected_session.connection.ext_out_queue.put(clipboard_data)
    await connected_session.connection.ext_out_queue.put(None)

    await asyncio.wait_for(drain_task, timeout=2.0)

    assert clipboard_texts == ["hello from remote"]


async def test_run_until_stopped_emits_video_frames(connected_session):
    """VIDEO queue items invoke registered video frame callbacks."""

    video_frames = []
    connected_session.add_video_frame_callback(video_frames.append)

    video_rectangle = aardwolf.commons.queuedata.video.RDP_VIDEO()
    video_rectangle.x = 10
    video_rectangle.y = 20
    video_rectangle.width = 8
    video_rectangle.height = 8
    video_rectangle.data = PIL.Image.new("RGBA", (8, 8))

    drain_task = asyncio.create_task(connected_session.run_until_stopped())

    await connected_session.connection.ext_out_queue.put(video_rectangle)
    await connected_session.connection.ext_out_queue.put(None)

    await asyncio.wait_for(drain_task, timeout=2.0)

    assert len(video_frames) == 1
    assert video_frames[0].x_position == 10
    assert video_frames[0].y_position == 20
