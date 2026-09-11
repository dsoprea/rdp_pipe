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
