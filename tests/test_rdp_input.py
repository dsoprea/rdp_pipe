"""Unit tests for shared RDP input message builders."""

import aardwolf.commons.queuedata.keyboard

import rdp_pipe.rdp_input


def test_build_named_key_messages_tab_uses_vk_only():
    """Named Tab keys must not carry a native scancode hint that can map to the wrong character."""

    messages = rdp_pipe.rdp_input.build_named_key_messages("Tab")

    assert len(messages) == 2
    assert messages[0].vk_code == "VK_TAB"
    assert messages[0].keyCode is None
    assert messages[1].vk_code == "VK_TAB"
    assert messages[1].keyCode is None


def test_build_ctrl_alt_del_messages_sequence():
    """Ctrl+Alt+Del chord presses modifiers then Delete and releases in reverse."""

    messages = rdp_pipe.rdp_input.build_ctrl_alt_del_messages()

    assert len(messages) == 6
    assert messages[0].vk_code == "VK_LCONTROL"
    assert messages[0].is_pressed is True
    assert messages[1].vk_code == "VK_LMENU"
    assert messages[1].is_pressed is True
    assert messages[2].vk_code == "VK_DELETE"
    assert messages[2].is_pressed is True
    assert messages[3].vk_code == "VK_DELETE"
    assert messages[3].is_pressed is False
    assert messages[4].vk_code == "VK_LMENU"
    assert messages[4].is_pressed is False
    assert messages[5].vk_code == "VK_LCONTROL"
    assert messages[5].is_pressed is False

    for keyboard_message in messages:
        assert isinstance(
            keyboard_message,
            aardwolf.commons.queuedata.keyboard.RDP_KEYBOARD_SCANCODE)


def test_build_windows_super_key_messages_press_and_release():
    """Windows Super key sends one press and one release."""

    messages = rdp_pipe.rdp_input.build_windows_super_key_messages()

    assert len(messages) == 2
    assert messages[0].vk_code == "VK_LWIN"
    assert messages[0].is_pressed is True
    assert messages[1].vk_code == "VK_LWIN"
    assert messages[1].is_pressed is False
