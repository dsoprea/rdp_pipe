"""Connection progress step identifiers and display labels for the GUI overlay."""

CONNECTION_STEP_RECONNECTING = "reconnecting"
CONNECTION_STEP_PREPARING = "preparing"
CONNECTION_STEP_CONNECTING = "connecting"
CONNECTION_STEP_VERIFYING_CERTIFICATE = "verifying_certificate"
CONNECTION_STEP_AUTHENTICATING = "authenticating"
CONNECTION_STEP_CONFIGURING_DISPLAY = "configuring_display"
CONNECTION_STEP_READY = "ready"

ORDERED_CONNECTION_STEPS = [
    CONNECTION_STEP_RECONNECTING,
    CONNECTION_STEP_PREPARING,
    CONNECTION_STEP_CONNECTING,
    CONNECTION_STEP_VERIFYING_CERTIFICATE,
    CONNECTION_STEP_AUTHENTICATING,
    CONNECTION_STEP_CONFIGURING_DISPLAY,
    CONNECTION_STEP_READY,
]

CONNECTION_STEP_LABELS = {
    CONNECTION_STEP_RECONNECTING: "Reconnecting to server",
    CONNECTION_STEP_PREPARING: "Preparing connection",
    CONNECTION_STEP_CONNECTING: "Connecting to server",
    CONNECTION_STEP_VERIFYING_CERTIFICATE: "Verifying server certificate",
    CONNECTION_STEP_AUTHENTICATING: "Authenticating",
    CONNECTION_STEP_CONFIGURING_DISPLAY: "Configuring display",
    CONNECTION_STEP_READY: "Ready",
}


def get_connection_step_label(step_identifier: str) -> str:
    """Return the operator-facing label for a connection progress step."""

    try:
        return CONNECTION_STEP_LABELS[step_identifier]

    except KeyError:
        raise ValueError(
            "unknown connection progress step {step_identifier}".format(
                step_identifier=step_identifier))


def get_connection_step_index(step_identifier: str) -> int:
    """Return the zero-based index of a step in the connect sequence."""

    try:
        return ORDERED_CONNECTION_STEPS.index(step_identifier)

    except ValueError:
        raise ValueError(
            "unknown connection progress step {step_identifier}".format(
                step_identifier=step_identifier))
