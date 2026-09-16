"""Unix domain socket JSON-line command server for RDP automation."""

import asyncio
import datetime
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback

import rdp_pipe.rdp_input
import rdp_pipe.rdp_session_core
import rdp_pipe.runtime_paths


_LOGGER = logging.getLogger(__name__)

COMMAND_HANDLER_TIMEOUT_SECONDS = 30.0

SUPPORTED_COMMANDS = (
    "receive_screenshot",
    "send_click",
    "receive_geometry",
    "send_geometry",
    "send_key",
)


def build_success_response(result: dict) -> str:
    """Serialize a successful command response."""

    response_body = {
        "ok": True,
        "result": result,
    }

    return json.dumps(response_body, separators=(",", ":"))


def build_error_response(error_message: str) -> str:
    """Serialize a failed command response."""

    response_body = {
        "ok": False,
        "error": error_message,
    }

    return json.dumps(response_body, separators=(",", ":"))


def parse_command_request(request_line: str) -> dict:
    """Parse one JSON-line command request."""

    if request_line == "":
        raise ValueError("empty request line")

    request_body = json.loads(request_line)

    if "command" not in request_body:
        raise ValueError("request missing command field")

    return request_body


def extract_command_name_from_request_line(request_line: str) -> str:
    """Return the command field from a request line, or unknown when not parseable."""

    if request_line == "":
        return "unknown"

    try:
        request_body = json.loads(request_line)

    except json.JSONDecodeError:
        return "unknown"

    try:
        return request_body["command"]

    except KeyError:
        return "unknown"


def build_command_transaction_log_line(
        timestamp_text: str,
        command_name: str,
        request_size: int,
        response_size: int,
        response_success: bool,
        transaction_duration_seconds: float) -> str:
    """Serialize one headless command transaction log entry as a JSON line."""

    log_body = {
        "timestamp": timestamp_text,
        "command": command_name,
        "request_size": request_size,
        "response_size": response_size,
        "response_success": response_success,
        "transaction_duration_seconds": round(transaction_duration_seconds, 2),
    }

    log_line = json.dumps(log_body, separators=(",", ":"))
    log_line = log_line + "\n"

    return log_line


def write_command_transaction_log_line(log_line: str):
    """Write one transaction log JSON line to stdout for headless operators."""

    sys.stdout.write(log_line)
    sys.stdout.flush()


DEFAULT_COMMAND_SOCKET_PATH = \
    rdp_pipe.runtime_paths.build_default_command_socket_filepath()


class CommandSocketClientError(Exception):
    """Remote command socket returned ok false or an invalid response envelope."""


def build_command_request_body(command_name: str, **fields) -> dict:
    """Build one wire-protocol command request object."""

    request_body = {"command": command_name}

    for field_name in fields.keys():
        request_body[field_name] = fields[field_name]

    return request_body


def send_command_request(socket_path: str, request_body: dict) -> dict:
    """Send one JSON-line command and return the parsed response envelope."""

    request_line = json.dumps(request_body, separators=(",", ":"))
    request_line = request_line + "\n"

    client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client_socket.connect(socket_path)

    try:
        client_socket.sendall(request_line.encode("utf-8"))

        response_buffer = b""

        while b"\n" not in response_buffer:
            received_chunk = client_socket.recv(4096)

            if received_chunk == b"":
                raise ConnectionError(
                    "command socket closed before response line for command {command_name}".format(
                        command_name=request_body["command"]))

            response_buffer = response_buffer + received_chunk

        response_line = response_buffer.split(b"\n", 1)[0].decode("utf-8")
        response_body = json.loads(response_line)

    finally:
        client_socket.close()

    if "ok" not in response_body:
        raise CommandSocketClientError(
            "command socket response missing ok field for command {command_name}".format(
                command_name=request_body["command"]))

    if response_body["ok"] is False:
        error_message = response_body["error"]
        raise CommandSocketClientError(error_message)

    return response_body


class CommandSocketServer:
    """Serve newline-delimited JSON commands over a Unix domain socket."""

    def __init__(
            self,
            socket_path: str,
            session: rdp_pipe.rdp_session_core.RdpAsyncSession,
            *,
            log_command_transactions: bool = False):
        """Bind session handlers to a Unix socket at socket_path."""

        self._socket_path = socket_path
        self._session = session
        self._log_command_transactions = log_command_transactions
        self._stop_event = threading.Event()
        self._server_thread = None
        self._listen_socket = None

    def start(self):
        """Start accepting command socket clients on a background thread."""

        self._server_thread = threading.Thread(
            target=self._server_thread_main,
            name="rdp-command-socket")

        self._server_thread.start()

    def set_session(self, session: rdp_pipe.rdp_session_core.RdpAsyncSession):
        """Point automation commands at a new session after reconnect."""

        self._session = session

    def stop(self):
        """Stop the accept loop and close the listening socket."""

        self._stop_event.set()

        if self._listen_socket is not None:
            try:
                self._listen_socket.close()

            except OSError:
                pass

        if self._server_thread is not None:
            self._server_thread.join(timeout=2.0)

    def _server_thread_main(self):
        """Accept one client at a time and process JSON-line commands."""

        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        self._listen_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listen_socket.bind(self._socket_path)
        self._listen_socket.listen(1)

        while not self._stop_event.is_set():
            try:
                self._listen_socket.settimeout(1.0)
                client_socket, _client_address = self._listen_socket.accept()

            except (TimeoutError, socket.timeout):
                continue

            except OSError:
                if self._stop_event.is_set():
                    break

                raise

            self._serve_client(client_socket)
            client_socket.close()

    def _serve_client(self, client_socket: socket.socket):
        """Read requests from one client until disconnect."""

        input_file = client_socket.makefile(mode="r", encoding="utf-8")
        output_file = client_socket.makefile(mode="w", encoding="utf-8")

        try:
            while not self._stop_event.is_set():
                request_line = input_file.readline()

                if request_line == "":
                    return

                request_payload = request_line.rstrip("\n")
                request_size = len(request_payload.encode("utf-8"))
                transaction_started_at = time.perf_counter()
                response_line = self._dispatch_request_line(request_payload)
                transaction_duration_seconds = \
                    time.perf_counter() - transaction_started_at

                output_file.write(response_line)
                output_file.write("\n")
                output_file.flush()

                if self._log_command_transactions:
                    response_size = len(response_line.encode("utf-8"))
                    response_body = json.loads(response_line)
                    response_success = response_body["ok"]
                    command_name = extract_command_name_from_request_line(request_payload)
                    timestamp_text = \
                        datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(
                            timespec="milliseconds")
                    log_line = build_command_transaction_log_line(
                        timestamp_text,
                        command_name,
                        request_size,
                        response_size,
                        response_success,
                        transaction_duration_seconds)

                    write_command_transaction_log_line(log_line)

        finally:
            input_file.close()
            output_file.close()

    def _dispatch_request_line(self, request_line: str) -> str:
        """Parse and execute one command request."""

        try:
            request_body = parse_command_request(request_line)

        except ValueError as error:
            return build_error_response(str(error))

        except json.JSONDecodeError as error:
            return build_error_response(
                "invalid JSON: {message}".format(message=str(error)))

        command_name = request_body["command"]

        if command_name not in SUPPORTED_COMMANDS:
            return build_error_response(
                "unknown command {command_name}".format(command_name=command_name))

        try:
            result = self._execute_command_on_session_loop(request_body)

            return build_success_response(result)

        except rdp_pipe.rdp_input.RdpInputError as error:
            return build_error_response(str(error))

        except rdp_pipe.rdp_session_core.RdpSessionError as error:
            return build_error_response(str(error))

        except Exception as error:
            traceback.print_exc()

            return build_error_response(
                "command failed: {message}".format(message=str(error)))

    def _execute_command_on_session_loop(self, request_body: dict) -> dict:
        """Marshal command execution onto the RDP asyncio loop."""

        event_loop = self._session.event_loop
        if event_loop is None:
            raise rdp_pipe.rdp_session_core.RdpSessionError(
                "RDP session is reconnecting")

        command_future = asyncio.run_coroutine_threadsafe(
            self._handle_command(request_body),
            event_loop)

        return command_future.result(timeout=COMMAND_HANDLER_TIMEOUT_SECONDS)

    async def _handle_command(self, request_body: dict) -> dict:
        """Dispatch a parsed command to the session."""

        command_name = request_body["command"]

        if command_name == "receive_screenshot":
            image_format = "png"
            if "format" in request_body:
                image_format = request_body["format"]

            quality = 9
            if "quality" in request_body:
                quality = int(request_body["quality"])

            return await self._session.handle_receive_screenshot(
                image_format,
                quality)

        if command_name == "receive_geometry":
            return await self._session.handle_receive_geometry()

        if command_name == "send_geometry":
            width_value = None
            height_value = None

            try:
                width_value = int(request_body["width"])
            except KeyError:
                pass

            try:
                height_value = int(request_body["height"])
            except KeyError:
                pass

            return await self._session.handle_send_geometry(
                width_value,
                height_value)

        if command_name == "send_click":
            if "x" not in request_body or "y" not in request_body:
                raise ValueError("send_click requires x and y")

            button = "left"
            if "button" in request_body:
                button = request_body["button"]

            return await self._session.handle_send_click(
                int(request_body["x"]),
                int(request_body["y"]),
                button)

        if command_name == "send_key":
            keys_value = None
            key_value = None

            if "keys" in request_body:
                keys_value = request_body["keys"]

            if "key" in request_body:
                key_value = request_body["key"]

            return await self._session.handle_send_key(keys_value, key_value)

        raise ValueError(
            "unsupported command {command_name}".format(command_name=command_name))
