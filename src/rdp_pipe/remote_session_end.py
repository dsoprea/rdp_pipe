"""ERRINFO values that should prompt the GUI reconnect-or-exit dialog."""

RECONNECT_PROMPT_ERRINFO_NAMES = frozenset({
    "SERVER_SHUTDOWN",
    "SERVER_REBOOT",
})


def is_reconnect_prompt_errinfo(error_info_name: str) -> bool:
    """Return True when the server signaled host shutdown or reboot."""

    return error_info_name in RECONNECT_PROMPT_ERRINFO_NAMES


def record_reconnect_prompt_errinfo_on_connection(connection) -> None:
    """Copy logon_error onto pending_remote_session_end_reason when applicable."""

    if hasattr(connection, "pending_remote_session_end_reason") is False:
        return

    logon_error = connection.logon_error

    if logon_error is None:
        return

    if is_reconnect_prompt_errinfo(logon_error.name):
        connection.pending_remote_session_end_reason = logon_error.name


def build_reconnect_policy_dialog_title(errinfo_name: str) -> str:
    """Return a title-case dialog title for shutdown or reboot ERRINFO."""

    if errinfo_name == "SERVER_SHUTDOWN":
        return "Remote System Shutting Down"

    if errinfo_name == "SERVER_REBOOT":
        return "Remote System Restarting"

    return "Remote Session Ended"


def build_reconnect_policy_dialog_message(errinfo_name: str) -> str:
    """Return dialog body text explaining the drop and asking to reconnect."""

    if errinfo_name == "SERVER_SHUTDOWN":
        return (
            "The remote system is shutting down and the RDP session has ended. "
            "Keep trying to reconnect until it is back, or exit the client.")

    if errinfo_name == "SERVER_REBOOT":
        return (
            "The remote system is restarting and the RDP session has ended. "
            "Keep trying to reconnect until it is back, or exit the client.")

    return (
        "The RDP session ended unexpectedly. "
        "Keep trying to reconnect, or exit the client.")
