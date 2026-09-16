"""Default filesystem paths under the system temp directory."""

import os
import tempfile


COMMAND_SOCKET_FILENAME = "rdp.sock"
ACTIVITY_STAMP_FILENAME = "rdp_activity.stamp"


def get_system_temp_directory_path() -> str:
    """Return the process system temp directory path."""

    return tempfile.gettempdir()


def build_default_command_socket_filepath() -> str:
    """Return the default Unix domain socket filepath for command automation."""

    return os.path.join(
        get_system_temp_directory_path(),
        COMMAND_SOCKET_FILENAME)


def build_default_activity_stamp_filepath() -> str:
    """Return the default activity stamp filepath for framebuffer updates."""

    return os.path.join(
        get_system_temp_directory_path(),
        ACTIVITY_STAMP_FILENAME)
