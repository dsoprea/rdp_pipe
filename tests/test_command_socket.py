"""Unit tests for command socket protocol helpers."""

import asyncio
import io
import json
import os
import socket
import tempfile
import threading

import PIL.Image
import pytest

import rdp_pipe.command_socket
import rdp_pipe.rdp_input
import rdp_pipe.rdp_session_core


def test_build_command_request_body():
    """Request bodies include command and optional fields."""

    request_body = rdp_pipe.command_socket.build_command_request_body(
        "send_click",
        x=10,
        y=20,
        button="left")

    assert request_body == {
        "command": "send_click",
        "x": 10,
        "y": 20,
        "button": "left",
    }


def test_send_command_request_success():
    """Client reads one success response line from the socket."""

    temporary_directory = tempfile.mkdtemp()
    socket_path = os.path.join(temporary_directory, "rdp.sock")

    ready_event = threading.Event()

    def server_thread_main():
        listen_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listen_socket.bind(socket_path)
        listen_socket.listen(1)
        ready_event.set()

        client_socket, _client_address = listen_socket.accept()

        input_file = client_socket.makefile(mode="r", encoding="utf-8")
        request_line = input_file.readline()
        input_file.close()

        assert request_line == '{"command":"receive_geometry"}\n'

        response_line = rdp_pipe.command_socket.build_success_response(
            {"width": 1280, "height": 800, "color_depth": 32})

        client_socket.sendall((response_line + "\n").encode("utf-8"))
        client_socket.close()
        listen_socket.close()

    server_thread = threading.Thread(target=server_thread_main)
    server_thread.start()
    ready_event.wait(timeout=2.0)

    response_body = rdp_pipe.command_socket.send_command_request(
        socket_path,
        {"command": "receive_geometry"})

    server_thread.join(timeout=2.0)

    assert response_body["ok"] is True
    assert response_body["result"]["width"] == 1280


def test_send_command_request_error_raises():
    """Client raises CommandSocketClientError when ok is false."""

    temporary_directory = tempfile.mkdtemp()
    socket_path = os.path.join(temporary_directory, "rdp.sock")

    ready_event = threading.Event()

    def server_thread_main():
        listen_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listen_socket.bind(socket_path)
        listen_socket.listen(1)
        ready_event.set()

        client_socket, _client_address = listen_socket.accept()

        input_file = client_socket.makefile(mode="r", encoding="utf-8")
        input_file.readline()
        input_file.close()

        response_line = rdp_pipe.command_socket.build_error_response("bad command")
        client_socket.sendall((response_line + "\n").encode("utf-8"))
        client_socket.close()
        listen_socket.close()

    server_thread = threading.Thread(target=server_thread_main)
    server_thread.start()
    ready_event.wait(timeout=2.0)

    with pytest.raises(rdp_pipe.command_socket.CommandSocketClientError) as error_info:
        rdp_pipe.command_socket.send_command_request(
            socket_path,
            {"command": "receive_geometry"})

    server_thread.join(timeout=2.0)

    assert str(error_info.value) == "bad command"


def test_build_success_response():
    """Success responses include ok and result."""

    response_line = rdp_pipe.command_socket.build_success_response(
        {"width": 1280, "height": 800})

    response_body = json.loads(response_line)

    assert response_body["ok"] is True
    assert response_body["result"]["width"] == 1280


def test_build_error_response():
    """Error responses include ok false and an error string."""

    response_line = rdp_pipe.command_socket.build_error_response("bad command")

    response_body = json.loads(response_line)

    assert response_body["ok"] is False
    assert response_body["error"] == "bad command"


def test_parse_command_request_requires_command_field():
    """Requests without command are rejected."""

    with pytest.raises(ValueError):
        rdp_pipe.command_socket.parse_command_request("{}")


def test_parse_command_request_invalid_json():
    """Invalid JSON is rejected by json.loads in dispatch."""

    with pytest.raises(json.JSONDecodeError):
        rdp_pipe.command_socket.parse_command_request("{not-json")


def test_extract_command_name_from_request_line_valid():
    """Valid requests return the command field."""

    command_name = rdp_pipe.command_socket.extract_command_name_from_request_line(
        '{"command":"receive_geometry"}')

    assert command_name == "receive_geometry"


def test_extract_command_name_from_request_line_unknown():
    """Invalid or incomplete requests return unknown."""

    assert rdp_pipe.command_socket.extract_command_name_from_request_line("") == "unknown"
    assert rdp_pipe.command_socket.extract_command_name_from_request_line("{not-json") == "unknown"
    assert rdp_pipe.command_socket.extract_command_name_from_request_line("{}") == "unknown"


def test_build_command_transaction_log_line():
    """Transaction log lines include required fields with two-decimal duration."""

    log_line = rdp_pipe.command_socket.build_command_transaction_log_line(
        "2026-09-16T10:53:00.123-04:00",
        "receive_geometry",
        32,
        58,
        True,
        0.05123)

    log_body = json.loads(log_line)

    assert log_body["timestamp"] == "2026-09-16T10:53:00.123-04:00"
    assert log_body["command"] == "receive_geometry"
    assert log_body["request_size"] == 32
    assert log_body["response_size"] == 58
    assert log_body["response_success"] is True
    assert log_body["transaction_duration_seconds"] == 0.05
    assert log_line.endswith("\n")


def test_encode_desktop_image_png_base64_round_trip():
    """PNG encoding produces decodable image bytes."""

    desktop_image = PIL.Image.new("RGBA", (4, 4), color=(255, 0, 0, 255))

    image_bytes = rdp_pipe.rdp_session_core.encode_desktop_image(
        desktop_image,
        "png",
        9)

    round_trip_image = PIL.Image.open(io.BytesIO(image_bytes))

    assert round_trip_image.size == (4, 4)


def test_build_mouse_click_messages_invalid_button():
    """Unsupported mouse buttons raise RdpInputError."""

    with pytest.raises(rdp_pipe.rdp_input.RdpInputError):
        rdp_pipe.rdp_input.build_mouse_click_messages(10, 20, "side")


def test_build_named_key_messages_return_and_escape():
    """Named keys map to press and release scancode messages."""

    messages = rdp_pipe.rdp_input.build_named_key_messages("Return")

    assert len(messages) == 2
    assert messages[0].vk_code == "VK_RETURN"
    assert messages[0].is_pressed is True
    assert messages[1].is_pressed is False


def test_build_text_key_messages_unicode_pairs():
    """Text keys emit press and release per character."""

    messages = rdp_pipe.rdp_input.build_text_key_messages("ab")

    assert len(messages) == 4
    assert messages[0].char == "a"
    assert messages[1].char == "a"
    assert messages[2].char == "b"


def test_dispatch_request_from_background_thread_uses_stored_event_loop():
    """Command socket threads must not call asyncio.get_running_loop() on the session."""

    async def run_command_socket_dispatch_from_worker_thread():
        session = rdp_pipe.rdp_session_core.RdpAsyncSession(
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

        command_server = rdp_pipe.command_socket.CommandSocketServer(
            "/tmp/test-rdp-command-socket.sock",
            session)

        response_line = await asyncio.to_thread(
            command_server._dispatch_request_line,
            '{"command":"receive_geometry"}')

        response_body = json.loads(response_line)

        assert response_body["ok"] is True
        assert response_body["result"]["width"] == 1280

    asyncio.run(run_command_socket_dispatch_from_worker_thread())
