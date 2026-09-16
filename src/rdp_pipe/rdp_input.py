"""Shared RDP mouse and keyboard message builders for GUI and command socket."""

import aardwolf.commons.queuedata.constants
import aardwolf.commons.queuedata.keyboard
import aardwolf.commons.queuedata.mouse


MOUSE_BUTTON_NAME_TO_ENUM = {
    "left": aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_LEFT,
    "right": aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_RIGHT,
    "middle": aardwolf.commons.queuedata.constants.MOUSEBUTTON.MOUSEBUTTON_MIDDLE,
}

NAMED_KEY_TO_VK_CODE = {
    "Return": "VK_RETURN",
    "Enter": "VK_RETURN",
    "Escape": "VK_ESCAPE",
    "Tab": "VK_TAB",
    "Backspace": "VK_BACK",
    "Delete": "VK_DELETE",
    "Insert": "VK_INSERT",
    "Home": "VK_HOME",
    "End": "VK_END",
    "PageUp": "VK_PRIOR",
    "PageDown": "VK_NEXT",
    "Left": "VK_LEFT",
    "Up": "VK_UP",
    "Right": "VK_RIGHT",
    "Down": "VK_DOWN",
    "F1": "VK_F1",
    "F2": "VK_F2",
    "F3": "VK_F3",
    "F4": "VK_F4",
    "F5": "VK_F5",
    "F6": "VK_F6",
    "F7": "VK_F7",
    "F8": "VK_F8",
    "F9": "VK_F9",
    "F10": "VK_F10",
    "F11": "VK_F11",
    "F12": "VK_F12",
}


class RdpInputError(ValueError):
    """Raised when automation input parameters are invalid."""


def build_mouse_click_messages(x_position: int, y_position: int, button_name: str) -> list:
    """Return press and release RDP_MOUSE messages for a click."""

    normalized_button_name = button_name.lower()
    if normalized_button_name not in MOUSE_BUTTON_NAME_TO_ENUM.keys():
        raise RdpInputError(
            "unsupported mouse button {button_name}; use left, right, or middle".format(
                button_name=button_name))

    mouse_button = MOUSE_BUTTON_NAME_TO_ENUM[normalized_button_name]

    press_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
    press_message.xPos = x_position
    press_message.yPos = y_position
    press_message.button = mouse_button
    press_message.is_pressed = True

    release_message = aardwolf.commons.queuedata.mouse.RDP_MOUSE()
    release_message.xPos = x_position
    release_message.yPos = y_position
    release_message.button = mouse_button
    release_message.is_pressed = False

    return [press_message, release_message]


def build_named_key_messages(key_name: str) -> list:
    """Return press and release scancode messages for a named key."""

    if key_name not in NAMED_KEY_TO_VK_CODE.keys():
        raise RdpInputError(
            "unsupported key name {key_name}".format(key_name=key_name))

    vk_code = NAMED_KEY_TO_VK_CODE[key_name]

    press_message = aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_SCANCODE()
    press_message.vk_code = vk_code
    press_message.is_pressed = True

    release_message = aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_SCANCODE()
    release_message.vk_code = vk_code
    release_message.is_pressed = False

    return [press_message, release_message]


def build_text_key_messages(text: str) -> list:
    """Return unicode key press and release messages for each character."""

    messages = []

    for character in text:
        press_message = aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_UNICODE()
        press_message.char = character
        press_message.is_pressed = True
        messages.append(press_message)

        release_message = aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_UNICODE()
        release_message.char = character
        release_message.is_pressed = False
        messages.append(release_message)

    return messages
