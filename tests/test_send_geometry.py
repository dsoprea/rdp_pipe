"""Unit tests for send_geometry command handling."""

import asyncio
import unittest.mock

import pytest

import rdp_pipe.command_socket
import rdp_pipe.rdp_session_core


def test_handle_send_geometry_resets_native_resolution():
    """Omitted dimensions request the initial connect resolution."""

    session = rdp_pipe.rdp_session_core.RdpAsyncSession(
        "rdp+ntlm-password://user@10.0.0.1",
        1280,
        800)

    display_control_channel = unittest.mock.AsyncMock()
    display_control_channel.request_resolution = unittest.mock.AsyncMock(return_value=True)
    session._display_control_channel = display_control_channel

    result = asyncio.run(session.handle_send_geometry())

    display_control_channel.request_resolution.assert_awaited_once_with(1280, 800)
    assert result == {"width": 1280, "height": 800}


def test_handle_send_geometry_requests_explicit_dimensions():
    """Width and height are forwarded to RDPDISP after clamping."""

    session = rdp_pipe.rdp_session_core.RdpAsyncSession(
        "rdp+ntlm-password://user@10.0.0.1",
        1280,
        800)

    display_control_channel = unittest.mock.AsyncMock()
    display_control_channel.request_resolution = unittest.mock.AsyncMock(return_value=True)
    session._display_control_channel = display_control_channel

    result = asyncio.run(session.handle_send_geometry(1921, 900))

    display_control_channel.request_resolution.assert_awaited_once_with(1921, 900)
    assert result == {"width": 1920, "height": 900}


def test_handle_send_geometry_rejects_partial_dimensions():
    """Only one of width or height is invalid."""

    session = rdp_pipe.rdp_session_core.RdpAsyncSession(
        "rdp+ntlm-password://user@10.0.0.1",
        1280,
        800)

    session._display_control_channel = unittest.mock.AsyncMock()

    with pytest.raises(ValueError):
        asyncio.run(session.handle_send_geometry(1920, None))


def test_handle_send_geometry_fails_without_rdpsisp_caps():
    """Unavailable RDPDISP caps surface as RdpSessionError."""

    session = rdp_pipe.rdp_session_core.RdpAsyncSession(
        "rdp+ntlm-password://user@10.0.0.1",
        1280,
        800)

    display_control_channel = unittest.mock.AsyncMock()
    display_control_channel.request_resolution = unittest.mock.AsyncMock(return_value=False)
    session._display_control_channel = display_control_channel

    with pytest.raises(rdp_pipe.rdp_session_core.RdpSessionError):
        asyncio.run(session.handle_send_geometry(1600, 900))


def test_command_socket_handle_send_geometry():
    """Command handler routes send_geometry to the session."""

    session = unittest.mock.Mock()
    session.handle_send_geometry = unittest.mock.AsyncMock(
        return_value={"width": 1280, "height": 800})

    command_server = rdp_pipe.command_socket.CommandSocketServer(
        "/tmp/test-rdp.sock",
        session)

    request_body = {"command": "send_geometry", "width": 1280, "height": 800}
    result = asyncio.run(command_server._handle_command(request_body))

    assert result == {"width": 1280, "height": 800}
    session.handle_send_geometry.assert_awaited_once_with(1280, 800)


def test_command_socket_handle_send_geometry_native_reset():
    """Omitted width and height pass None to the session handler."""

    session = unittest.mock.Mock()
    session.handle_send_geometry = unittest.mock.AsyncMock(
        return_value={"width": 1280, "height": 800})

    command_server = rdp_pipe.command_socket.CommandSocketServer(
        "/tmp/test-rdp.sock",
        session)

    request_body = {"command": "send_geometry"}
    result = asyncio.run(command_server._handle_command(request_body))

    assert result == {"width": 1280, "height": 800}
    session.handle_send_geometry.assert_awaited_once_with(None, None)
