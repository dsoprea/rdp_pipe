"""Format negotiated server RDP capabilities for operator stderr after connect."""

import enum
import sys


def _format_capability_field_value(field_value):
    """Render one capability field for operator-readable stderr."""

    if isinstance(field_value, enum.IntFlag):
        flag_names = [flag_member.name for flag_member in field_value]

        if len(flag_names) == 0:
            return "0"

        return "|".join(flag_names)

    if isinstance(field_value, enum.Enum):
        return field_value.name

    if isinstance(field_value, bytes):
        return "bytes(length={length})".format(length=len(field_value))

    return repr(field_value)


def _resolve_connect_gcc_serverdata(server_connect_pdu):
    """Return the GCC server userdata map from aardwolf's stored connect PDU."""

    if server_connect_pdu is None:
        return None

    if isinstance(server_connect_pdu, dict):
        return server_connect_pdu

    try:
        serverdata = server_connect_pdu.serverdata
    except AttributeError:
        return None

    return serverdata


def _format_userdata_type_sort_key(userdata_type_key):
    """Sort GCC userdata block keys whether they are enums or plain strings."""

    try:
        return userdata_type_key.value
    except AttributeError:
        return str(userdata_type_key)


def _format_userdata_type_name(userdata_type):
    """Return a label for one GCC userdata block key."""

    try:
        return userdata_type.name
    except AttributeError:
        return str(userdata_type)


def _format_userdata_block_lines(userdata_block):
    """Return indented lines describing one GCC server userdata block."""

    lines = []

    for field_name in userdata_block.__dict__.keys():
        if field_name == "type":
            continue

        field_value = userdata_block.__dict__[field_name]
        formatted_value = _format_capability_field_value(field_value)
        lines.append(
            "  {field_name}: {formatted_value}".format(
                field_name=field_name,
                formatted_value=formatted_value))

    return lines


def _format_connect_gcc_server_data_lines(server_connect_pdu):
    """Return lines for T.124 server connect userdata blocks."""

    lines = ["Connect GCC server data:"]

    serverdata = _resolve_connect_gcc_serverdata(server_connect_pdu)

    if serverdata is None:
        lines.append("  (unavailable)")

        return lines

    if len(serverdata) == 0:
        lines.append("  (empty)")

        return lines

    for userdata_type in sorted(
            serverdata.keys(),
            key=_format_userdata_type_sort_key):

        userdata_block = serverdata[userdata_type]
        block_name = _format_userdata_type_name(userdata_type)
        lines.append("  {block_name}:".format(block_name=block_name))
        block_lines = _format_userdata_block_lines(userdata_block)
        lines.extend(block_lines)

    return lines


def _format_demand_active_capability_set_lines(capability_set):
    """Return lines for one Demand Active TS_CAPS_SET entry."""

    capability_type_name = capability_set.capabilitySetType.name
    lines = ["  {capability_type_name}:".format(
        capability_type_name=capability_type_name)]

    capability = capability_set.capability

    if capability is None:
        lines.append(
            "    (unparsed, length={length})".format(
                length=capability_set.lengthCapability))

        return lines

    for field_name in capability.__dict__.keys():
        field_value = capability.__dict__[field_name]
        formatted_value = _format_capability_field_value(field_value)
        lines.append(
            "    {field_name}: {formatted_value}".format(
                field_name=field_name,
                formatted_value=formatted_value))

    return lines


def _format_demand_active_lines(demand_active_pdu):
    """Return lines for capability sets in the server Demand Active PDU."""

    lines = ["Demand Active capability sets:"]

    if demand_active_pdu is None:
        lines.append("  (not captured)")

        return lines

    if len(demand_active_pdu.capabilitySets) == 0:
        lines.append("  (empty)")

        return lines

    for capability_set in demand_active_pdu.capabilitySets:
        set_lines = _format_demand_active_capability_set_lines(capability_set)
        lines.extend(set_lines)

    return lines


def _format_display_control_caps_lines(display_control_caps):
    """Return lines for RDPDISP DISPLAYCONTROL_CAPS_PDU when present."""

    lines = ["RDPDISP display control:"]

    if display_control_caps is None:
        lines.append("  (not advertised)")

        return lines

    lines.append(
        "  max_num_monitors: {max_num_monitors}".format(
            max_num_monitors=display_control_caps.max_num_monitors))
    lines.append(
        "  max_monitor_area_factor_a: {factor_a}".format(
            factor_a=display_control_caps.max_monitor_area_factor_a))
    lines.append(
        "  max_monitor_area_factor_b: {factor_b}".format(
            factor_b=display_control_caps.max_monitor_area_factor_b))

    return lines


def build_server_capability_report_lines(connection):
    """Assemble stderr lines for server capabilities after a successful connect."""

    server_connect_pdu = getattr(
        connection,
        "_RDPConnection__server_connect_pdu",
        None)
    demand_active_pdu = getattr(connection, "_server_demand_active_pdu", None)
    display_control_channel = getattr(connection, "display_control_channel", None)
    display_control_caps = None

    if display_control_channel is not None:
        display_control_caps = display_control_channel._caps

    report_lines = ["Server capabilities:"]
    report_lines.append("")
    gcc_lines = _format_connect_gcc_server_data_lines(server_connect_pdu)
    report_lines.extend(gcc_lines)
    report_lines.append("")
    demand_active_lines = _format_demand_active_lines(demand_active_pdu)
    report_lines.extend(demand_active_lines)
    report_lines.append("")
    display_control_lines = _format_display_control_caps_lines(display_control_caps)
    report_lines.extend(display_control_lines)
    report_lines.append("")

    return report_lines


def write_server_capability_report_to_stderr(connection):
    """Print the server capability report to stderr."""

    report_lines = build_server_capability_report_lines(connection)

    for report_line in report_lines:
        sys.stderr.write(report_line)
        sys.stderr.write("\n")
