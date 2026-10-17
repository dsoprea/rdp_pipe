"""Tests for remote session ERRINFO handling."""

import unittest.mock

import aardwolf.protocol.T128.seterrorinfopdu

import rdp_pipe.remote_session_end
import rdp_pipe.rdp_connection


def test_is_reconnect_prompt_errinfo_shutdown_and_reboot():
    """Only host shutdown and reboot ERRINFO names qualify for the GUI prompt."""

    assert rdp_pipe.remote_session_end.is_reconnect_prompt_errinfo("SERVER_SHUTDOWN") is True
    assert rdp_pipe.remote_session_end.is_reconnect_prompt_errinfo("SERVER_REBOOT") is True
    assert rdp_pipe.remote_session_end.is_reconnect_prompt_errinfo("LOGOFF_BY_USER") is False


def test_record_reconnect_prompt_errinfo_on_connection():
    """logon_error is copied to pending_remote_session_end_reason when applicable."""

    connection = unittest.mock.Mock()
    connection.pending_remote_session_end_reason = None
    connection.logon_error = aardwolf.protocol.T128.seterrorinfopdu.ERRINFO.SERVER_REBOOT

    rdp_pipe.remote_session_end.record_reconnect_prompt_errinfo_on_connection(connection)

    assert connection.pending_remote_session_end_reason == "SERVER_REBOOT"


def test_patched_check_logon_status_sets_pending_reason_on_desktop_connection():
    """check_logon_status patch records SERVER_SHUTDOWN on RdpDesktopConnection."""

    connection = unittest.mock.Mock()
    connection.pending_remote_session_end_reason = None
    connection.logon_error = None

    def _fake_original_check_logon_status(_self, _data):
        _self.logon_error = aardwolf.protocol.T128.seterrorinfopdu.ERRINFO.SERVER_SHUTDOWN

    with unittest.mock.patch.object(
            rdp_pipe.rdp_connection,
            "_ORIGINAL_CHECK_LOGON_STATUS",
            _fake_original_check_logon_status):

        rdp_pipe.rdp_connection._patched_check_logon_status(connection, b"")

    assert connection.pending_remote_session_end_reason == "SERVER_SHUTDOWN"


def test_patched_check_logon_status_ignores_logoff_errinfo():
    """LOGOFF_BY_USER does not set pending_remote_session_end_reason."""

    connection = unittest.mock.Mock()
    connection.pending_remote_session_end_reason = None

    def _fake_original_check_logon_status(_self, _data):
        _self.logon_error = aardwolf.protocol.T128.seterrorinfopdu.ERRINFO.LOGOFF_BY_USER

    with unittest.mock.patch.object(
            rdp_pipe.rdp_connection,
            "_ORIGINAL_CHECK_LOGON_STATUS",
            _fake_original_check_logon_status):

        rdp_pipe.rdp_connection._patched_check_logon_status(connection, b"")

    assert connection.pending_remote_session_end_reason is None
