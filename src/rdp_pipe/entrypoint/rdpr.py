"""Send one remote command to a running rdp session over its command socket."""

import argparse
import base64
import json
import sys
import tempfile

import rdp_pipe.command_socket


def build_subcommand_name(wire_command_name: str) -> str:
    """Map a wire command name to an rdpr subcommand name."""

    return "command_{wire_command_name}".format(wire_command_name=wire_command_name)


def wire_command_name_from_subcommand(subcommand_name: str) -> str:
    """Strip the command_ prefix from a subcommand name."""

    prefix = "command_"

    if subcommand_name.startswith(prefix) is False:
        raise ValueError(
            "subcommand {subcommand_name} is missing command_ prefix".format(
                subcommand_name=subcommand_name))

    return subcommand_name[len(prefix):]


def register_receive_geometry_subparser(subparsers) -> None:
    """Register command_receive_geometry."""

    subcommand_name = build_subcommand_name("receive_geometry")

    subparsers.add_parser(
        subcommand_name,
        help="return remote session width, height, and color depth")


def register_send_geometry_subparser(subparsers) -> None:
    """Register command_send_geometry."""

    subcommand_name = build_subcommand_name("send_geometry")

    send_geometry_parser = subparsers.add_parser(
        subcommand_name,
        help="request remote resolution change via RDPDISP, or reset native size when omitted")

    send_geometry_parser.add_argument(
        "width",
        nargs="?",
        type=int,
        help="target width in pixels (requires height)")

    send_geometry_parser.add_argument(
        "height",
        nargs="?",
        type=int,
        help="target height in pixels (requires width)")


def register_receive_screenshot_subparser(subparsers) -> None:
    """Register command_receive_screenshot."""

    subcommand_name = build_subcommand_name("receive_screenshot")

    receive_screenshot_parser = subparsers.add_parser(
        subcommand_name,
        help="capture the remote framebuffer to a temporary PNG or JPEG file")

    receive_screenshot_parser.add_argument(
        "--format",
        default="png",
        help="image format: png or jpeg (default png)")

    receive_screenshot_parser.add_argument(
        "--quality",
        type=int,
        default=9,
        help="PNG compress level 0-9 or JPEG quality 1-95 (default 9)")


def register_send_click_subparser(subparsers) -> None:
    """Register command_send_click."""

    subcommand_name = build_subcommand_name("send_click")

    send_click_parser = subparsers.add_parser(
        subcommand_name,
        help="send a mouse click at remote coordinates")

    send_click_parser.add_argument(
        "x",
        type=int,
        help="horizontal pixel coordinate")

    send_click_parser.add_argument(
        "y",
        type=int,
        help="vertical pixel coordinate")

    send_click_parser.add_argument(
        "--button",
        default="left",
        help="mouse button: left, right, or middle (default left)")


def register_send_key_subparser(subparsers) -> None:
    """Register command_send_key."""

    subcommand_name = build_subcommand_name("send_key")

    send_key_parser = subparsers.add_parser(
        subcommand_name,
        help="send keyboard input as text or a named key")

    send_key_parser.add_argument(
        "keys",
        nargs="?",
        help="unicode text to type")

    send_key_parser.add_argument(
        "--key",
        help="named special key such as Return or Escape")


SUBPARSER_REGISTRARS_BY_WIRE_COMMAND = {
    "receive_geometry": register_receive_geometry_subparser,
    "send_geometry": register_send_geometry_subparser,
    "receive_screenshot": register_receive_screenshot_subparser,
    "send_click": register_send_click_subparser,
    "send_key": register_send_key_subparser,
}


def build_argument_parser() -> argparse.ArgumentParser:
    """Build argparse parser with -h help."""

    parser = argparse.ArgumentParser(
        description="Send one automation command to a running rdp session.")

    parser.add_argument(
        "--sock-filepath",
        dest="sock_filepath",
        default=rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH,
        help="Unix domain socket for JSON-line automation (default {0})".format(
            rdp_pipe.command_socket.DEFAULT_COMMAND_SOCKET_PATH))

    subparsers = parser.add_subparsers(
        dest="subcommand",
        required=True)

    for wire_command_name in rdp_pipe.command_socket.SUPPORTED_COMMANDS:
        register_subparser = SUBPARSER_REGISTRARS_BY_WIRE_COMMAND[wire_command_name]
        register_subparser(subparsers)

    return parser


def validate_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace):
    """Enforce subcommand-specific argument rules."""

    if arguments.subcommand == build_subcommand_name("send_key"):
        if arguments.keys is not None and arguments.key is not None:
            parser.error("command_send_key accepts keys or --key, not both")

        if arguments.keys is None and arguments.key is None:
            parser.error("command_send_key requires keys or --key")

    if arguments.subcommand == build_subcommand_name("send_geometry"):
        width_present = arguments.width is not None
        height_present = arguments.height is not None

        if width_present != height_present:
            parser.error(
                "command_send_geometry requires both width and height, or neither to reset native resolution")


def build_request_body_for_arguments(arguments: argparse.Namespace) -> dict:
    """Build the wire-protocol request body from parsed CLI arguments."""

    wire_command_name = wire_command_name_from_subcommand(arguments.subcommand)

    if wire_command_name == "receive_geometry":
        return rdp_pipe.command_socket.build_command_request_body("receive_geometry")

    if wire_command_name == "send_geometry":
        if arguments.width is None and arguments.height is None:
            return rdp_pipe.command_socket.build_command_request_body("send_geometry")

        return rdp_pipe.command_socket.build_command_request_body(
            "send_geometry",
            width=arguments.width,
            height=arguments.height)

    if wire_command_name == "receive_screenshot":
        return rdp_pipe.command_socket.build_command_request_body(
            "receive_screenshot",
            format=arguments.format,
            quality=arguments.quality)

    if wire_command_name == "send_click":
        return rdp_pipe.command_socket.build_command_request_body(
            "send_click",
            x=arguments.x,
            y=arguments.y,
            button=arguments.button)

    if wire_command_name == "send_key":
        if arguments.keys is not None:
            return rdp_pipe.command_socket.build_command_request_body(
                "send_key",
                keys=arguments.keys)

        return rdp_pipe.command_socket.build_command_request_body(
            "send_key",
            key=arguments.key)

    raise ValueError(
        "unsupported subcommand {subcommand_name}".format(
            subcommand_name=arguments.subcommand))


def write_receive_screenshot_result_to_temp_file(result: dict) -> tuple[str, float]:
    """Decode base64 screenshot bytes and write them to a temporary file."""

    image_format = result["format"]
    encoded_data = result["data"]

    # Decode wire-protocol base64 and persist image bytes using the server format.
    image_bytes = base64.standard_b64decode(encoded_data)
    temporary_file = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".{0}".format(image_format))

    try:
        temporary_file.write(image_bytes)

    finally:
        temporary_file.close()

    screenshot_filepath = temporary_file.name
    bytes_written = len(image_bytes)
    megabytes_written = bytes_written / (1024 * 1024)

    return screenshot_filepath, megabytes_written


def print_receive_screenshot_result(result: dict) -> None:
    """Write decoded screenshot data to a temp file and print path and size."""

    screenshot_filepath, megabytes_written = \
        write_receive_screenshot_result_to_temp_file(result)

    sys.stdout.write(
        "{filepath}\n".format(filepath=screenshot_filepath))
    sys.stderr.write(
        "Image size: {megabytes:.2f}\n".format(megabytes=megabytes_written))
    sys.stderr.write("\n")


def main(argv: list[str] | None = None) -> int:
    """Parse argv, send one remote command, and print the JSON response."""

    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    validate_arguments(parser, arguments)

    request_body = build_request_body_for_arguments(arguments)

    try:
        response_body = rdp_pipe.command_socket.send_command_request(
            arguments.sock_filepath,
            request_body)

    except rdp_pipe.command_socket.CommandSocketClientError as error:
        sys.stderr.write(
            "error: {message}\n".format(message=str(error)))

        return 1

    wire_command_name = wire_command_name_from_subcommand(arguments.subcommand)

    if wire_command_name == "receive_screenshot":
        print_receive_screenshot_result(response_body["result"])

        return 0

    response_line = json.dumps(response_body, separators=(",", ":"))
    sys.stdout.write(response_line)
    sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
