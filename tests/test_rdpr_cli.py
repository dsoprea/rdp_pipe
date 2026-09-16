"""CLI validation tests for rdpr."""

import base64
import os

import pytest

import rdp_pipe.command_socket
import rdp_pipe.entrypoint.rdpr


def test_default_sock_filepath():
    """Default socket path is /tmp/rdp.sock when omitted."""

    parser = rdp_pipe.entrypoint.rdpr.build_argument_parser()
    arguments = parser.parse_args(["command_receive_geometry"])

    assert arguments.sock_filepath == rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH


def test_sock_filepath_override():
    """Parent --sock-filepath applies to subcommands."""

    parser = rdp_pipe.entrypoint.rdpr.build_argument_parser()
    arguments = parser.parse_args(
        ["--sock-filepath", "/run/user/1000/rdp.sock", "command_receive_geometry"])

    assert arguments.sock_filepath == "/run/user/1000/rdp.sock"


def test_help_flag_exits_successfully():
    """-h prints usage and exits zero."""

    with pytest.raises(SystemExit) as exit_info:
        rdp_pipe.entrypoint.rdpr.main(["-h"])

    assert exit_info.value.code == 0


def test_send_key_requires_keys_or_key():
    """command_send_key without keys or --key is rejected."""

    with pytest.raises(SystemExit):
        rdp_pipe.entrypoint.rdpr.main(["command_send_key"])


def test_send_key_rejects_both_keys_and_key():
    """command_send_key rejects keys and --key together."""

    with pytest.raises(SystemExit):
        rdp_pipe.entrypoint.rdpr.main(
            ["command_send_key", "hello", "--key", "Return"])


def test_send_geometry_rejects_partial_dimensions():
    """command_send_geometry rejects only one of width or height."""

    with pytest.raises(SystemExit):
        rdp_pipe.entrypoint.rdpr.main(["command_send_geometry", "1920"])


def test_build_request_body_receive_geometry():
    """receive_geometry maps to a wire command body."""

    parser = rdp_pipe.entrypoint.rdpr.build_argument_parser()
    arguments = parser.parse_args(["command_receive_geometry"])

    request_body = rdp_pipe.entrypoint.rdpr.build_request_body_for_arguments(
        arguments)

    assert request_body == {"command": "receive_geometry"}


def test_build_request_body_send_geometry_native_reset():
    """send_geometry with no dimensions omits width and height."""

    parser = rdp_pipe.entrypoint.rdpr.build_argument_parser()
    arguments = parser.parse_args(["command_send_geometry"])

    request_body = rdp_pipe.entrypoint.rdpr.build_request_body_for_arguments(
        arguments)

    assert request_body == {"command": "send_geometry"}


def test_build_request_body_send_geometry_explicit():
    """send_geometry forwards width and height."""

    parser = rdp_pipe.entrypoint.rdpr.build_argument_parser()
    arguments = parser.parse_args(["command_send_geometry", "1920", "1080"])

    request_body = rdp_pipe.entrypoint.rdpr.build_request_body_for_arguments(
        arguments)

    assert request_body == {
        "command": "send_geometry",
        "width": 1920,
        "height": 1080,
    }


def test_build_request_body_send_click():
    """send_click maps coordinates and button to the wire body."""

    parser = rdp_pipe.entrypoint.rdpr.build_argument_parser()
    arguments = parser.parse_args(["command_send_click", "100", "200", "--button", "right"])

    request_body = rdp_pipe.entrypoint.rdpr.build_request_body_for_arguments(
        arguments)

    assert request_body == {
        "command": "send_click",
        "x": 100,
        "y": 200,
        "button": "right",
    }


def test_supported_commands_have_subparsers():
    """Every supported wire command has an rdpr subcommand registrar."""

    assert set(rdp_pipe.entrypoint.rdpr.SUBPARSER_REGISTRARS_BY_WIRE_COMMAND.keys()) \
        == set(rdp_pipe.command_socket.SUPPORTED_COMMANDS)


def test_receive_screenshot_writes_temp_file_and_prints_size(
        monkeypatch,
        capsys):
    """command_receive_screenshot decodes data, writes a temp file, and prints size."""

    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    encoded_data = base64.standard_b64encode(image_bytes).decode("ascii")
    response_body = {
        "ok": True,
        "result": {
            "width": 1280,
            "height": 800,
            "format": "png",
            "data": encoded_data,
        },
    }

    def fake_send_command_request(_socket_path, _request_body):
        return response_body

    monkeypatch.setattr(
        rdp_pipe.command_socket,
        "send_command_request",
        fake_send_command_request)

    exit_code = rdp_pipe.entrypoint.rdpr.main(
        ["command_receive_screenshot", "--format", "png"])

    captured = capsys.readouterr()
    stdout_lines = captured.out.splitlines()
    stderr_lines = captured.err.splitlines()

    assert exit_code == 0
    assert len(stdout_lines) == 1
    assert stdout_lines[0].endswith(".png")
    assert os.path.isfile(stdout_lines[0])

    with open(stdout_lines[0], "rb") as screenshot_file:
        written_bytes = screenshot_file.read()

    assert written_bytes == image_bytes

    expected_megabytes = len(image_bytes) / (1024 * 1024)
    assert len(stderr_lines) == 2
    assert stderr_lines[1] == ""
    assert stderr_lines[0] == "Image size: {0:.2f}".format(expected_megabytes)

    os.remove(stdout_lines[0])


def test_receive_screenshot_no_write_prints_json_response(
        monkeypatch,
        capsys):
    """command_receive_screenshot --no-write prints the full JSON envelope."""

    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    encoded_data = base64.standard_b64encode(image_bytes).decode("ascii")
    response_body = {
        "ok": True,
        "result": {
            "width": 1280,
            "height": 800,
            "format": "png",
            "data": encoded_data,
        },
    }

    def fake_send_command_request(_socket_path, _request_body):
        return response_body

    monkeypatch.setattr(
        rdp_pipe.command_socket,
        "send_command_request",
        fake_send_command_request)

    exit_code = rdp_pipe.entrypoint.rdpr.main(
        ["command_receive_screenshot", "--format", "png", "--no-write"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == \
        '{"ok":true,"result":{"width":1280,"height":800,"format":"png","data":"' \
        + encoded_data \
        + '"}}\n'
    assert captured.err == ""
