"""Offline tests for the MCP server helpers in mcp/server.py."""

import importlib.util
import json
import os
import subprocess

import mcp.server.mcpserver.exceptions
import mcp_types
import pytest


def load_mcp_server_module():
    """Load mcp/server.py as a test module without shadowing the PyPI mcp package."""

    repository_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_filepath = os.path.join(repository_root, "mcp", "server.py")
    module_spec = importlib.util.spec_from_file_location("rdp_pipe_mcp_server", module_filepath)
    mcp_server_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(mcp_server_module)

    return mcp_server_module


mcp_server_module = load_mcp_server_module()


def test_receive_screenshot_argv_always_includes_no_write():
    """Screenshot argv must always pass --no-write for inline image ingestion."""

    argv = mcp_server_module.build_receive_screenshot_argv("/tmp/rdp.sock", "png", 9)

    assert "--no-write" in argv
    assert argv[-1] == "--no-write"


def test_receive_screenshot_argv_includes_format_and_quality():
    """Screenshot argv forwards format and quality to rdpr."""

    argv = mcp_server_module.build_receive_screenshot_argv("/tmp/rdp.sock", "jpeg", 80)

    assert argv == [
        "rdpr",
        "--sock-filepath",
        "/tmp/rdp.sock",
        "command_receive_screenshot",
        "--format",
        "jpeg",
        "--quality",
        "80",
        "--no-write",
    ]


def test_build_screenshot_tool_contents_png_mime_type():
    """PNG screenshots map to image/png MCP content."""

    encoded_data = "aGVsbG8="
    response_body = {
        "ok": True,
        "result": {
            "width": 1280,
            "height": 800,
            "format": "png",
            "data": encoded_data,
        },
    }

    contents = mcp_server_module.build_screenshot_tool_contents(response_body)

    assert len(contents) == 2
    assert isinstance(contents[0], mcp_types.ImageContent)
    assert contents[0].mime_type == "image/png"
    assert contents[0].data == encoded_data
    assert isinstance(contents[1], mcp_types.TextContent)
    assert json.loads(contents[1].text) == {
        "width": 1280,
        "height": 800,
        "format": "png",
    }


def test_build_screenshot_tool_contents_jpeg_mime_type():
    """JPEG screenshots map to image/jpeg MCP content."""

    response_body = {
        "ok": True,
        "result": {
            "width": 640,
            "height": 480,
            "format": "jpeg",
            "data": "abc123",
        },
    }

    contents = mcp_server_module.build_screenshot_tool_contents(response_body)

    assert contents[0].mime_type == "image/jpeg"


def test_validate_send_key_rejects_both_keys_and_key():
    """send_key validation rejects supplying keys and key together."""

    with pytest.raises(ValueError, match="not both"):
        mcp_server_module.validate_send_key_arguments("hello", "Return")


def test_validate_send_key_requires_one_input():
    """send_key validation requires keys or key."""

    with pytest.raises(ValueError, match="requires keys or key"):
        mcp_server_module.validate_send_key_arguments(None, None)


def test_validate_send_geometry_rejects_width_without_height():
    """send_geometry validation rejects a lone width."""

    with pytest.raises(ValueError, match="both width and height"):
        mcp_server_module.validate_send_geometry_arguments(1920, None)


def test_run_rdpr_and_return_json_envelope_propagates_nonzero_exit(monkeypatch):
    """Non-zero rdpr exit codes surface as MCP tool errors."""

    def fake_run_rdpr_subcommand(_argv):
        return 1, "", "error: command socket unavailable\n"

    monkeypatch.setattr(mcp_server_module, "run_rdpr_subcommand", fake_run_rdpr_subcommand)

    with pytest.raises(mcp.server.mcpserver.exceptions.ToolError, match="command socket unavailable"):
        mcp_server_module.run_rdpr_and_return_json_envelope(["rdpr", "command_receive_geometry"])


def test_run_rdpr_subcommand_uses_subprocess_without_shell(monkeypatch):
    """rdpr subprocess invocation uses argv lists and never shell=True."""

    captured = {}

    def fake_run(argv, capture_output, text, timeout, check):
        captured["argv"] = argv
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        captured["check"] = check

        completed = subprocess.CompletedProcess(argv, 0, stdout='{"ok":true,"result":{}}\n', stderr="")

        return completed

    monkeypatch.setattr(mcp_server_module.subprocess, "run", fake_run)

    returncode, stdout, stderr = mcp_server_module.run_rdpr_subcommand(
        ["rdpr", "--sock-filepath", "/tmp/rdp.sock", "command_send_key", "hello"])

    assert returncode == 0
    assert stdout == '{"ok":true,"result":{}}\n'
    assert stderr == ""
    assert captured["argv"] == [
        "rdpr",
        "--sock-filepath",
        "/tmp/rdp.sock",
        "command_send_key",
        "hello",
    ]
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == mcp_server_module.RDPR_SUBPROCESS_TIMEOUT_SECONDS
    assert captured["check"] is False
