"""CLI validation tests for rdp."""

import pytest

import rdp_client.entrypoint.rdp


def test_headless_requires_pipe():
    """--headless without --pipe is rejected."""

    with pytest.raises(SystemExit):
        rdp_client.entrypoint.rdp.main(
            ["--headless", "10.0.0.5"])


def test_pipe_without_headless_parses():
    """GUI mode accepts optional --pipe with the default socket path."""

    parser = rdp_client.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--pipe", "10.0.0.5"])

    assert arguments.headless is False
    assert arguments.pipe is True


def test_headless_with_pipe_parses():
    """Headless mode accepts --pipe."""

    parser = rdp_client.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--headless", "--pipe", "10.0.0.5"])

    assert arguments.headless is True
    assert arguments.pipe is True


def test_activity_stamp_filepath_parses():
    """--activity-stamp-filepath is accepted in GUI and headless modes."""

    parser = rdp_client.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        [
            "--activity-stamp-filepath",
            "/tmp/rdp-activity",
            "10.0.0.5",
        ])

    assert arguments.activity_stamp_filepath == "/tmp/rdp-activity"

    headless_arguments = parser.parse_args(
        [
            "--headless",
            "--pipe",
            "--activity-stamp-filepath",
            "/tmp/rdp-activity",
            "10.0.0.5",
        ])

    assert headless_arguments.activity_stamp_filepath == "/tmp/rdp-activity"


def test_write_connection_progress_to_stderr_writes_step_label(capsys):
    """Headless progress callback prints operator-facing step labels."""

    import rdp_client.connection_progress

    rdp_client.entrypoint.rdp.write_connection_progress_to_stderr(
        rdp_client.connection_progress.CONNECTION_STEP_AUTHENTICATING)

    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "Authenticating\n"


def test_help_flag_exits_successfully():
    """-h prints usage and exits zero."""

    with pytest.raises(SystemExit) as exit_info:
        rdp_client.entrypoint.rdp.main(["-h"])

    assert exit_info.value.code == 0


def test_color_depth_default_is_32():
    """--color-depth defaults to 32 bpp."""

    parser = rdp_client.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(["10.0.0.5"])

    assert arguments.color_depth == rdp_client.entrypoint.rdp.DEFAULT_COLOR_DEPTH


def test_color_depth_parses():
    """--color-depth accepts supported bpp values."""

    parser = rdp_client.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--color-depth", "24", "10.0.0.5"])

    assert arguments.color_depth == 24
