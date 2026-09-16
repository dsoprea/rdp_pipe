"""Unit tests for automatic session reconnect."""

import asyncio
import unittest.mock

import pytest

import rdp_client.connection_error
import rdp_client.connection_progress
import rdp_client.rdp_session_thread


@pytest.mark.asyncio
async def test_run_connection_reconnects_after_disconnect(monkeypatch):
    """A dropped session tears down and schedules another connect attempt."""

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()
    worker.set_session(
        "rdp+ntlm-password://user:secret@10.0.0.7",
        1280,
        800,
        unittest.mock.Mock(),
        color_depth=32)

    connect_attempt_count = 0
    progress_step_identifiers = []

    def record_progress(step_identifier: str):
        progress_step_identifiers.append(step_identifier)

    worker.connection_progress.connect(record_progress)

    class FakeAsyncSession:
        """Minimal session stub for reconnect loop tests."""

        def __init__(
                self,
                connection_url,
                video_width,
                video_height,
                color_depth=32,
                activity_stamp_filepath=None):

            self.display_caps_unavailable = False
            self._stop_event = asyncio.Event()

        def add_video_frame_callback(self, callback):
            pass

        def add_pointer_update_callback(self, callback):
            pass

        def add_resolution_changed_callback(self, callback):
            pass

        def set_progress_callback(self, callback):
            pass

        async def connect(self):
            nonlocal connect_attempt_count

            connect_attempt_count = connect_attempt_count + 1

            if connect_attempt_count >= 2:
                worker._gui_stopped_event.set()

        async def drain_queued_pointer_updates(self):
            pass

        async def run_until_stopped(self):
            pass

        async def stop(self):
            self._stop_event.set()

    monkeypatch.setattr(
        rdp_client.rdp_session_core,
        "RdpAsyncSession",
        FakeAsyncSession)
    monkeypatch.setattr(
        rdp_client.rdp_session_thread,
        "SESSION_RECONNECT_DELAY_SECONDS",
        0.0)
    monkeypatch.setattr(
        rdp_client.rdp_session_thread,
        "SESSION_RECONNECT_POLL_SECONDS",
        0.0)

    await worker._run_connection()

    assert connect_attempt_count == 2
    assert rdp_client.connection_progress.CONNECTION_STEP_RECONNECTING in progress_step_identifiers


@pytest.mark.asyncio
async def test_wait_before_reconnect_honors_shutdown():
    """Reconnect delay exits early when the GUI requests shutdown."""

    worker = rdp_client.rdp_session_thread.RdpSessionWorker()
    worker._gui_stopped_event.set()

    await worker._wait_before_reconnect()


def test_format_session_disconnected_reconnecting_stderr():
    """Clean disconnects print a reconnecting stderr line with host:port."""

    stderr_text = \
        rdp_client.connection_error.format_session_disconnected_reconnecting_stderr(
            "rdp+ntlm-password://user:secret@10.0.0.7:3390")

    assert stderr_text == \
        "error: RDP session to 10.0.0.7:3390 disconnected; reconnecting...\n"
