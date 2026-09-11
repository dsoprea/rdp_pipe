"""CLI validation tests for rdp."""

import pytest

import rdp_client.entrypoint.rdp


def test_headless_requires_command_socket():
    """--headless without --command-socket is rejected."""

    with pytest.raises(SystemExit):
        rdp_client.entrypoint.rdp.main(
            ["--headless", "10.0.0.5"])


def test_command_socket_without_headless_parses():
    """GUI mode accepts optional --command-socket."""

    parser = rdp_client.entrypoint.rdp.build_argument_parser()
    arguments = parser.parse_args(
        ["--command-socket", "/tmp/rdp.sock", "10.0.0.5"])

    assert arguments.headless is False
    assert arguments.command_socket_path == "/tmp/rdp.sock"


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
