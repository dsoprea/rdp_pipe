"""Unit tests for activity stamp file touches."""

import os
import time

import rdp_pipe.activity_stamp


def test_touch_activity_stamp_file_creates_file(tmp_path):
    """Touch creates an empty stamp file when it does not exist."""

    activity_stamp_filepath = os.path.join(str(tmp_path), "activity.stamp")

    rdp_pipe.activity_stamp.touch_activity_stamp_file(activity_stamp_filepath)

    assert os.path.isfile(activity_stamp_filepath)
    assert os.path.getsize(activity_stamp_filepath) == 0


def test_touch_activity_stamp_file_updates_mtime(tmp_path):
    """A second touch advances the file modification time."""

    activity_stamp_filepath = os.path.join(str(tmp_path), "activity.stamp")

    rdp_pipe.activity_stamp.touch_activity_stamp_file(activity_stamp_filepath)
    first_mtime = os.path.getmtime(activity_stamp_filepath)

    time.sleep(0.05)

    rdp_pipe.activity_stamp.touch_activity_stamp_file(activity_stamp_filepath)
    second_mtime = os.path.getmtime(activity_stamp_filepath)

    assert second_mtime >= first_mtime
