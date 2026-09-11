"""Unit tests for command socket protocol helpers."""

import asyncio
import io
import json

import PIL.Image
import pytest

import rdp_client.command_socket
import rdp_client.rdp_input
import rdp_client.rdp_session_core


def test_build_success_response():
    """Success responses include ok and result."""

    response_line = rdp_client.command_socket.build_success_response(
        {"width": 1280, "height": 800})

    response_body = json.loads(response_line)

    assert response_body["ok"] is True
    assert response_body["result"]["width"] == 1280


def test_build_error_response():
    """Error responses include ok false and an error string."""

    response_line = rdp_client.command_socket.build_error_response("bad command")

    response_body = json.loads(response_line)

    assert response_body["ok"] is False
    assert response_body["error"] == "bad command"


def test_parse_command_request_requires_command_field():
    """Requests without command are rejected."""

    with pytest.raises(ValueError):
        rdp_client.command_socket.parse_command_request("{}")


def test_parse_command_request_invalid_json():
    """Invalid JSON is rejected by json.loads in dispatch."""

    with pytest.raises(json.JSONDecodeError):
        rdp_client.command_socket.parse_command_request("{not-json")


def test_encode_desktop_image_png_base64_round_trip():
    """PNG encoding produces decodable image bytes."""

    desktop_image = PIL.Image.new("RGBA", (4, 4), color=(255, 0, 0, 255))

    image_bytes = rdp_client.rdp_session_core.encode_desktop_image(
        desktop_image,
        "png",
        9)

    round_trip_image = PIL.Image.open(io.BytesIO(image_bytes))

    assert round_trip_image.size == (4, 4)


def test_build_mouse_click_messages_invalid_button():
    """Unsupported mouse buttons raise RdpInputError."""

    with pytest.raises(rdp_client.rdp_input.RdpInputError):
        rdp_client.rdp_input.build_mouse_click_messages(10, 20, "side")


def test_build_named_key_messages_return_and_escape():
    """Named keys map to press and release scancode messages."""

    messages = rdp_client.rdp_input.build_named_key_messages("Return")

    assert len(messages) == 2
    assert messages[0].vk_code == "VK_RETURN"
    assert messages[0].is_pressed is True
    assert messages[1].is_pressed is False


def test_build_text_key_messages_unicode_pairs():
    """Text keys emit press and release per character."""

    messages = rdp_client.rdp_input.build_text_key_messages("ab")

    assert len(messages) == 4
    assert messages[0].char == "a"
    assert messages[1].char == "a"
    assert messages[2].char == "b"


def test_dispatch_request_from_background_thread_uses_stored_event_loop():
    """Command socket threads must not call asyncio.get_running_loop() on the session."""

    async def run_command_socket_dispatch_from_worker_thread():
        session = rdp_client.rdp_session_core.RdpAsyncSession(
            "rdp+ntlm-password://example.test",
            1280,
            800)
        session._event_loop = asyncio.get_running_loop()

        async def handle_receive_geometry():
            return {
                "width": 1280,
                "height": 800,
                "color_depth": 32,
            }

        session.handle_receive_geometry = handle_receive_geometry

        command_server = rdp_client.command_socket.CommandSocketServer(
            "/tmp/test-rdp-command-socket.sock",
            session)

        response_line = await asyncio.to_thread(
            command_server._dispatch_request_line,
            '{"command":"receive_geometry"}')

        response_body = json.loads(response_line)

        assert response_body["ok"] is True
        assert response_body["result"]["width"] == 1280

    asyncio.run(run_command_socket_dispatch_from_worker_thread())
