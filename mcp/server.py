"""MCP stdio server wrapping rdpr for RDP command-pipe automation."""

import json
import os
import subprocess

import mcp.server.mcpserver.exceptions
import mcp_types
import mcp.server.mcpserver
import rdp_pipe.command_socket

DEFAULT_RDPR_COMMAND = "rdpr"
DEFAULT_RDPR_SOCK_FILEPATH = rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH
RDPR_SUBPROCESS_TIMEOUT_SECONDS = 35


def resolve_rdpr_command() -> str:
    """Return the rdpr executable path from RDPR_COMMAND or the default."""

    return os.environ.get("RDPR_COMMAND", DEFAULT_RDPR_COMMAND)


def resolve_sock_filepath(sock_filepath: str | None) -> str:
    """Resolve the command socket path from a tool argument or environment."""

    if sock_filepath is not None:
        return sock_filepath

    return os.environ.get("RDPR_SOCK_FILEPATH", DEFAULT_RDPR_SOCK_FILEPATH)


def build_rdpr_base_argv(sock_filepath: str) -> list[str]:
    """Build argv prefix shared by every rdpr subcommand invocation."""

    return [
        resolve_rdpr_command(),
        "--sock-filepath",
        sock_filepath,
    ]


def build_receive_geometry_argv(sock_filepath: str) -> list[str]:
    """Build argv for rdpr command_receive_geometry."""

    argv = build_rdpr_base_argv(sock_filepath)
    argv.append("command_receive_geometry")

    return argv


def build_send_geometry_argv(
        sock_filepath: str,
        width: int | None,
        height: int | None) -> list[str]:
    """Build argv for rdpr command_send_geometry."""

    validate_send_geometry_arguments(width, height)

    argv = build_rdpr_base_argv(sock_filepath)
    argv.append("command_send_geometry")

    if width is not None and height is not None:
        argv.append(str(width))
        argv.append(str(height))

    return argv


def build_receive_screenshot_argv(
        sock_filepath: str,
        image_format: str,
        quality: int) -> list[str]:
    """Build argv for rdpr command_receive_screenshot with --no-write."""

    argv = build_rdpr_base_argv(sock_filepath)
    argv.append("command_receive_screenshot")
    argv.append("--format")
    argv.append(image_format)
    argv.append("--quality")
    argv.append(str(quality))
    argv.append("--no-write")

    return argv


def build_send_click_argv(
        sock_filepath: str,
        x: int,
        y: int,
        button: str) -> list[str]:
    """Build argv for rdpr command_send_click."""

    argv = build_rdpr_base_argv(sock_filepath)
    argv.append("command_send_click")
    argv.append(str(x))
    argv.append(str(y))
    argv.append("--button")
    argv.append(button)

    return argv


def build_send_key_argv(
        sock_filepath: str,
        keys: str | None,
        key: str | None) -> list[str]:
    """Build argv for rdpr command_send_key."""

    validate_send_key_arguments(keys, key)

    argv = build_rdpr_base_argv(sock_filepath)
    argv.append("command_send_key")

    if keys is not None:
        argv.append(keys)

    if key is not None:
        argv.append("--key")
        argv.append(key)

    return argv


def validate_send_geometry_arguments(width: int | None, height: int | None) -> None:
    """Enforce rdpr send_geometry width and height pairing."""

    width_present = width is not None
    height_present = height is not None

    if width_present != height_present:
        raise ValueError(
            "command_send_geometry requires both width and height, or neither to reset native resolution")


def validate_send_key_arguments(keys: str | None, key: str | None) -> None:
    """Enforce rdpr send_key keys versus key exclusivity."""

    if keys is not None and key is not None:
        raise ValueError("command_send_key accepts keys or key, not both")

    if keys is None and key is None:
        raise ValueError("command_send_key requires keys or key")


def run_rdpr_subcommand(argv: list[str]) -> tuple[int, str, str]:
    """Run rdpr and return exit code, stdout, and stderr."""

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=RDPR_SUBPROCESS_TIMEOUT_SECONDS,
        check=False)

    return completed.returncode, completed.stdout, completed.stderr


def parse_rdpr_json_stdout(stdout: str) -> dict:
    """Parse the JSON response envelope printed by rdpr on stdout."""

    stdout_line = stdout.strip()

    if stdout_line == "":
        raise ValueError("rdpr returned empty stdout")

    response_body = json.loads(stdout_line)

    return response_body


def build_image_mime_type(image_format: str) -> str:
    """Map wire screenshot format to an MCP image MIME type."""

    normalized_format = image_format.lower()

    if normalized_format == "png":
        return "image/png"

    if normalized_format in ("jpeg", "jpg"):
        return "image/jpeg"

    raise ValueError(
        "unsupported screenshot format {image_format}; use png or jpeg".format(
            image_format=image_format))


def build_screenshot_tool_contents(response_body: dict) -> list[mcp_types.ContentBlock]:
    """Convert a receive_screenshot JSON envelope into MCP image and metadata content."""

    result = response_body["result"]
    image_format = result["format"]
    mime_type = build_image_mime_type(image_format)
    metadata = {
        "width": result["width"],
        "height": result["height"],
        "format": image_format,
    }

    image_content = mcp_types.ImageContent(
        type="image",
        data=result["data"],
        mime_type=mime_type)
    metadata_content = mcp_types.TextContent(
        type="text",
        text=json.dumps(metadata, separators=(",", ":")))

    return [image_content, metadata_content]


def format_rdpr_failure(stderr: str, returncode: int) -> str:
    """Build a tool error message from rdpr stderr and exit code."""

    stderr_text = stderr.strip()

    if stderr_text != "":
        return stderr_text

    return "rdpr exited with code {returncode}".format(returncode=returncode)


def run_rdpr_and_return_json_envelope(argv: list[str]) -> str:
    """Run rdpr and return the stdout JSON envelope as text."""

    returncode, stdout, stderr = run_rdpr_subcommand(argv)

    if returncode != 0:
        raise mcp.server.mcpserver.exceptions.ToolError(
            format_rdpr_failure(stderr, returncode))

    return stdout.strip()


mcp_server = mcp.server.mcpserver.MCPServer(
    "rdp_pipe",
    instructions=(
        "Control a running rdp session over its Unix command socket via rdpr. "
        "Start rdp with --pipe first. Wire protocol: REMOTE_COMMAND_PROTOCOL.md."))


@mcp_server.tool(
    name="command_receive_geometry",
    description=(
        "Return remote session width, height, and color depth. "
        "CLI equivalent: rdpr command_receive_geometry"))
def command_receive_geometry(sock_filepath: str | None = None) -> str:
    """Query the current remote desktop geometry."""

    argv = build_receive_geometry_argv(resolve_sock_filepath(sock_filepath))

    return run_rdpr_and_return_json_envelope(argv)


@mcp_server.tool(
    name="command_send_geometry",
    description=(
        "Request a remote resolution change via RDPDISP, or reset native size when "
        "width and height are omitted. CLI equivalent: rdpr command_send_geometry [WIDTH HEIGHT]"))
def command_send_geometry(
        width: int | None = None,
        height: int | None = None,
        sock_filepath: str | None = None) -> str:
    """Change remote session geometry or reset to native resolution."""

    try:
        argv = build_send_geometry_argv(
            resolve_sock_filepath(sock_filepath),
            width,
            height)

    except ValueError as error:
        raise mcp.server.mcpserver.exceptions.ToolError(str(error)) from error

    return run_rdpr_and_return_json_envelope(argv)


@mcp_server.tool(
    name="command_receive_screenshot",
    description=(
        "Capture the remote framebuffer and return inline image data for LLM ingestion. "
        "Always uses --no-write (no temp file). "
        "CLI equivalent: rdpr command_receive_screenshot --format FORMAT --quality QUALITY --no-write"))
def command_receive_screenshot(
        format: str = "png",
        quality: int = 9,
        sock_filepath: str | None = None) -> list[mcp_types.ContentBlock]:
    """Capture the remote desktop and return image plus dimension metadata."""

    argv = build_receive_screenshot_argv(
        resolve_sock_filepath(sock_filepath),
        format,
        quality)

    returncode, stdout, stderr = run_rdpr_subcommand(argv)

    if returncode != 0:
        raise mcp.server.mcpserver.exceptions.ToolError(
            format_rdpr_failure(stderr, returncode))

    try:
        response_body = parse_rdpr_json_stdout(stdout)

    except (ValueError, json.JSONDecodeError) as error:
        raise mcp.server.mcpserver.exceptions.ToolError(
            "rdpr screenshot response was not valid JSON: {message}".format(
                message=str(error))) from error

    try:
        return build_screenshot_tool_contents(response_body)

    except (KeyError, ValueError) as error:
        raise mcp.server.mcpserver.exceptions.ToolError(
            "rdpr screenshot response missing expected fields: {message}".format(
                message=str(error))) from error


@mcp_server.tool(
    name="command_send_click",
    description=(
        "Send a mouse click at remote coordinates. "
        "CLI equivalent: rdpr command_send_click X Y --button BUTTON"))
def command_send_click(
        x: int,
        y: int,
        button: str = "left",
        sock_filepath: str | None = None) -> str:
    """Click at remote desktop coordinates."""

    argv = build_send_click_argv(
        resolve_sock_filepath(sock_filepath),
        x,
        y,
        button)

    return run_rdpr_and_return_json_envelope(argv)


@mcp_server.tool(
    name="command_send_key",
    description=(
        "Send keyboard input as literal text or a named special key. "
        "CLI equivalent: rdpr command_send_key KEYS or rdpr command_send_key --key KEY"))
def command_send_key(
        keys: str | None = None,
        key: str | None = None,
        sock_filepath: str | None = None) -> str:
    """Type text or press a named key on the remote desktop."""

    try:
        argv = build_send_key_argv(
            resolve_sock_filepath(sock_filepath),
            keys,
            key)

    except ValueError as error:
        raise mcp.server.mcpserver.exceptions.ToolError(str(error)) from error

    return run_rdpr_and_return_json_envelope(argv)


def main() -> None:
    """Run the MCP server on stdio."""

    mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
