"""Fast-path input PDU builder for mouse events."""

FASTPATH_INPUT_ACTION_FASTPATH = 0
FASTPATH_INPUT_ENCRYPTED = 0x2
FASTPATH_INPUT_SECURE_CHECKSUM = 0x1
FASTPATH_INPUT_EVENT_MOUSE = 0x1


def build_pointer_flags_for_mouse_button(button, is_pressed: bool, steps: int) -> int:
    """Build TS_POINTER_EVENT.pointerFlags from a queuedata mouse button."""

    import aardwolf.commons.queuedata.constants
    import aardwolf.protocol.pdu.input.mouse

    pointer_flags = 0

    if is_pressed:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.DOWN

    if button == aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.BUTTON1

    if button == aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.BUTTON2

    if button == aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_MIDDLE:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.BUTTON3

    if button == aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_HOVER:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.MOVE

    if button == aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.WHEEL
        pointer_flags = pointer_flags | (
            aardwolf.protocol.pdu.input.mouse.PTRFLAGS.WheelRotationMask & steps)

    if button == aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_WHEEL_DOWN:
        pointer_flags = pointer_flags | aardwolf.protocol.pdu.input.mouse.PTRFLAGS.WHEEL_NEGATIVE
        pointer_flags = pointer_flags | (
            aardwolf.protocol.pdu.input.mouse.PTRFLAGS.WheelRotationMask & steps)

    return pointer_flags


def build_fastpath_mouse_input_pdu(
        cryptolayer,
        pointer_flags: int,
        x_position: int,
        y_position: int) -> bytes:
    """Build a single-event fast-path mouse input PDU."""

    event_header = FASTPATH_INPUT_EVENT_MOUSE << 5
    fp_input_events = (
        bytes([event_header])
        + pointer_flags.to_bytes(2, byteorder="little", signed=False)
        + x_position.to_bytes(2, byteorder="little", signed=False)
        + y_position.to_bytes(2, byteorder="little", signed=False))

    fp_input_header = FASTPATH_INPUT_ACTION_FASTPATH | (1 << 2)

    if cryptolayer is None:
        total_length = 3 + len(fp_input_events)
        length_bytes = (0x8000 | total_length).to_bytes(2, byteorder="big", signed=False)

        return bytes([fp_input_header]) + length_bytes + fp_input_events

    fp_input_header = fp_input_header | (FASTPATH_INPUT_ENCRYPTED << 6)

    if cryptolayer.use_encrypted_mac:
        fp_input_header = fp_input_header | (FASTPATH_INPUT_SECURE_CHECKSUM << 6)
        data_signature = cryptolayer.calc_salted_mac(fp_input_events)
    else:
        data_signature = cryptolayer.calc_mac(fp_input_events)

    encrypted_events = cryptolayer.client_enc(fp_input_events)
    pdu_body = data_signature + encrypted_events
    total_length = 3 + len(pdu_body)
    length_bytes = (0x8000 | total_length).to_bytes(2, byteorder="big", signed=False)

    return bytes([fp_input_header]) + length_bytes + pdu_body
