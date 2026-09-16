"""Shared pytest fixtures for RDP session integration tests."""

import asyncio
import threading
import types

import pytest

import rdp_pipe.rdp_connection
import rdp_pipe.rdp_session_core

import tests.support.mock_rdp_connection


CONNECTION_URL = "rdp+ntlm-password://user:pass@10.0.0.5"


@pytest.fixture
def mock_rdp_connection():
    """Return a fresh mock connection with default 1280x800 geometry."""

    return tests.support.mock_rdp_connection.MockRdpConnection(
        1280,
        800)


def _patch_factory_from_url(monkeypatch, mock_connection):
    """Monkeypatch RdpDesktopConnectionFactory.from_url to return the mock."""

    def fake_from_url(connection_url, iosettings):
        stub_factory = types.SimpleNamespace()
        stub_factory.get_connection = \
            lambda copied_iosettings: mock_connection.bind_iosettings(copied_iosettings)

        return stub_factory

    monkeypatch.setattr(
        rdp_pipe.rdp_connection.RdpDesktopConnectionFactory,
        "from_url",
        staticmethod(fake_from_url))


@pytest.fixture
async def connected_session(monkeypatch, mock_rdp_connection):
    """Return an RdpAsyncSession after connect() against the mock connection."""

    _patch_factory_from_url(monkeypatch, mock_rdp_connection)

    session = rdp_pipe.rdp_session_core.RdpAsyncSession(
        CONNECTION_URL,
        1280,
        800)

    await session.connect()

    return session


@pytest.fixture
async def session_event_loop(monkeypatch, mock_rdp_connection):
    """Run a connected session on a background asyncio loop for socket dispatch tests."""

    _patch_factory_from_url(monkeypatch, mock_rdp_connection)

    ready_event = threading.Event()
    session_holder = {"session": None}
    loop_holder = {"loop": None}
    startup_error_holder = {"error": None}

    def background_loop_main():
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)
        loop_holder["loop"] = event_loop

        async def connect_session():
            session = rdp_pipe.rdp_session_core.RdpAsyncSession(
                CONNECTION_URL,
                1280,
                800)

            await session.connect()
            session_holder["session"] = session
            ready_event.set()

            await session.run_until_stopped()

        try:
            event_loop.run_until_complete(connect_session())

        except Exception as error:
            startup_error_holder["error"] = error
            ready_event.set()

        finally:
            event_loop.close()

    background_thread = threading.Thread(
        target=background_loop_main,
        name="rdp-test-session-loop")

    background_thread.start()

    ready_event.wait(timeout=5.0)

    if startup_error_holder["error"] is not None:
        raise startup_error_holder["error"]

    if session_holder["session"] is None:
        raise RuntimeError("session_event_loop fixture failed to connect mock session")

    yield session_holder["session"], loop_holder["loop"]

    stop_future = asyncio.run_coroutine_threadsafe(
        session_holder["session"].stop(),
        loop_holder["loop"])

    stop_future.result(timeout=5.0)
    background_thread.join(timeout=5.0)
