"""Unix socket end-to-end tests for CommandSocketServer dispatch."""

import asyncio
import io
import json
import os
import socket
import sys
import time

import pytest

import rdp_pipe.command_socket


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

    server = rdp_pipe.command_socket.CommandSocketServer(
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


@pytest.fixture
def command_socket_server_with_transaction_logs(session_event_loop, tmp_path):
    """Start CommandSocketServer that writes transaction JSON lines to stdout."""

    session, event_loop = session_event_loop
    socket_path = os.path.join(str(tmp_path), "rdp-test-transaction-log.sock")

    server = rdp_pipe.command_socket.CommandSocketServer(
        socket_path,
        session,
        log_command_transactions=True)

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


def test_command_socket_transaction_log_success(command_socket_server_with_transaction_logs):
    """Headless transaction logging writes one JSON line per command to stdout."""

    socket_path, _session, _event_loop = command_socket_server_with_transaction_logs
    request_body = {"command": "receive_geometry"}
    request_line = json.dumps(request_body, separators=(",", ":"))
    expected_request_size = len(request_line.encode("utf-8"))
    stdout_capture = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = stdout_capture

    try:
        response_body = _send_command(
            socket_path,
            request_body)

    finally:
        sys.stdout = original_stdout

    assert response_body["ok"] is True

    log_lines = stdout_capture.getvalue().splitlines()
    assert len(log_lines) == 1

    log_body = json.loads(log_lines[0])
    response_line = rdp_pipe.command_socket.build_success_response(response_body["result"])
    expected_response_size = len(response_line.encode("utf-8"))

    assert log_body["command"] == "receive_geometry"
    assert log_body["request_size"] == expected_request_size
    assert log_body["response_size"] == expected_response_size
    assert log_body["response_success"] is True
    assert log_body["transaction_duration_seconds"] >= 0
    assert "timestamp" in log_body


def test_command_socket_transaction_log_invalid_request(
        command_socket_server_with_transaction_logs):
    """Malformed requests still emit a transaction log line with response_success false."""

    socket_path, _session, _event_loop = command_socket_server_with_transaction_logs
    invalid_request_line = "{not-json"
    expected_request_size = len(invalid_request_line.encode("utf-8"))
    stdout_capture = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = stdout_capture

    client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client_socket.connect(socket_path)

    try:
        client_socket.sendall((invalid_request_line + "\n").encode("utf-8"))

        response_buffer = b""
        while b"\n" not in response_buffer:
            response_chunk = client_socket.recv(4096)
            if response_chunk == b"":
                break

            response_buffer = response_buffer + response_chunk

        response_line = response_buffer.decode("utf-8").strip()
        response_body = json.loads(response_line)

    finally:
        client_socket.close()
        sys.stdout = original_stdout

    assert response_body["ok"] is False

    log_lines = stdout_capture.getvalue().splitlines()
    assert len(log_lines) == 1

    log_body = json.loads(log_lines[0])
    expected_response_size = len(response_line.encode("utf-8"))

    assert log_body["command"] == "unknown"
    assert log_body["request_size"] == expected_request_size
    assert log_body["response_size"] == expected_response_size
    assert log_body["response_success"] is False
