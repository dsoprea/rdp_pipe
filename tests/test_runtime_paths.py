"""Tests for default runtime filesystem paths."""

import os
import tempfile

import rdp_pipe.runtime_paths


def test_build_default_command_socket_filepath_uses_system_temp():
    """Default command socket lives under the system temp directory."""

    expected_filepath = os.path.join(
        tempfile.gettempdir(),
        rdp_pipe.runtime_paths.COMMAND_SOCKET_FILENAME)

    assert rdp_pipe.runtime_paths.build_default_command_socket_filepath() \
        == expected_filepath


def test_build_default_activity_stamp_filepath_uses_system_temp():
    """Default activity stamp lives under the system temp directory."""

    expected_filepath = os.path.join(
        tempfile.gettempdir(),
        rdp_pipe.runtime_paths.ACTIVITY_STAMP_FILENAME)

    assert rdp_pipe.runtime_paths.build_default_activity_stamp_filepath() \
        == expected_filepath
