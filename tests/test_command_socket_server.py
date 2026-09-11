"""Unix socket end-to-end tests for CommandSocketServer dispatch."""

import asyncio
import json
import os
import socket
import time

import pytest

import rdp_client.command_socket


def _send_command(socket_path: str, request_body: dict) -> dict:
    """Send one JSON-line command and parse the response."""

    client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client_socket.connect(socket_path)

    try:
        request_line = json.dumps(request_body, separators=(",", ":"))
        request_bytes = (request_line + "\n").encode("utf-8")
        client_socket.sendall(request_bytes)

        response_buffer = b""
        while b"\n" not in response_buffer:
            response_chunk = client_socket.recv(4096)
            if response_chunk == b"":
                break

            response_buffer = response_buffer + response_chunk

        response_line = response_buffer.decode("utf-8").strip()
        return json.loads(response_line)

    finally:
        client_socket.close()


@pytest.fixture
def command_socket_server(session_event_loop, tmp_path):
    """Start CommandSocketServer bound to a temporary Unix socket."""

    session, event_loop = session_event_loop
    socket_path = os.path.join(str(tmp_path), "rdp-test.sock")

    server = rdp_client.command_socket.CommandSocketServer(
        socket_path,
        session)

    server.start()

    bind_deadline = time.monotonic() + 2.0
    while time.monotonic() < bind_deadline:
        if os.path.exists(socket_path):
            break

        time.sleep(0.01)

    if os.path.exists(socket_path) is False:
        raise RuntimeError("command socket server did not bind {socket_path}".format(
            socket_path=socket_path))

    yield socket_path, session, event_loop

    server.stop()


def test_command_socket_receive_geometry(command_socket_server):
    """receive_geometry returns session dimensions over the Unix socket."""

    socket_path, _session, _event_loop = command_socket_server

    response_body = _send_command(
        socket_path,
        {"command": "receive_geometry"})

    assert response_body["ok"] is True
    assert response_body["result"]["width"] == 1280
    assert response_body["result"]["height"] == 800
    assert response_body["result"]["color_depth"] == 32


def test_command_socket_receive_screenshot(command_socket_server):
    """receive_screenshot returns base64 PNG data over the Unix socket."""

    socket_path, _session, _event_loop = command_socket_server

    response_body = _send_command(
        socket_path,
        {"command": "receive_screenshot", "format": "png"})

    assert response_body["ok"] is True
    assert response_body["result"]["format"] == "png"
    assert response_body["result"]["width"] == 1280
    assert len(response_body["result"]["data"]) > 0


def test_command_socket_send_click(command_socket_server):
    """send_click succeeds and enqueues mouse input on the mock connection."""

    socket_path, session, _event_loop = command_socket_server

    response_body = _send_command(
        socket_path,
        {"command": "send_click", "x": 50, "y": 75, "button": "left"})

    assert response_body["ok"] is True
    assert response_body["result"] == {}

    first_message_future = asyncio.run_coroutine_threadsafe(
        session.connection.ext_in_queue.get(),
        session.event_loop)

    first_message = first_message_future.result(timeout=2.0)
    assert first_message is not None


def test_command_socket_send_key(command_socket_server):
    """send_key succeeds and enqueues keyboard input on the mock connection."""

    socket_path, session, _event_loop = command_socket_server

    response_body = _send_command(
        socket_path,
        {"command": "send_key", "keys": "x"})

    assert response_body["ok"] is True
    assert response_body["result"] == {}

    first_message_future = asyncio.run_coroutine_threadsafe(
        session.connection.ext_in_queue.get(),
        session.event_loop)

    first_message = first_message_future.result(timeout=2.0)
    assert first_message is not None


def test_command_socket_send_geometry(command_socket_server):
    """send_geometry returns clamped dimensions over the Unix socket."""

    socket_path, _session, _event_loop = command_socket_server

    response_body = _send_command(
        socket_path,
        {"command": "send_geometry", "width": 1601, "height": 900})

    assert response_body["ok"] is True
    assert response_body["result"]["width"] == 1600
    assert response_body["result"]["height"] == 900
