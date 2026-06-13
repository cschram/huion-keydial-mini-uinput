"""Tests for binding mouse scroll-wheel actions (notably to the dial).

A scroll token (SCROLL_UP/DOWN/LEFT/RIGHT) bound to a dial action or button is
emitted as a relative mouse-wheel movement instead of a key press.
"""

from unittest.mock import patch

import pytest
from evdev import ecodes

from huion_keydial_mini.config import Config
from huion_keydial_mini.hid_parser import EventType, InputEvent
from huion_keydial_mini.keybind_manager import (
    SCROLL_ACTIONS,
    KeybindManager,
    event_type_for_keys,
)
from huion_keydial_mini.keybind_manager import (
    EventType as BindEventType,
)
from huion_keydial_mini.uinput_handler import UInputHandler


@pytest.fixture
def scroll_config():
    return Config({
        'key_mappings': {
            'BUTTON_1': 'KEY_F1',
            'BUTTON_2': 'SCROLL_UP',
        },
        'sticky_key_mappings': {},
        'dial_settings': {
            'DIAL_CW': 'SCROLL_UP',
            'DIAL_CCW': 'SCROLL_DOWN',
            'DIAL_CLICK': 'BTN_MIDDLE',
            'sensitivity': 1.0,
        },
    })


@pytest.fixture
def keybind_manager(scroll_config, tmp_path):
    return KeybindManager(scroll_config, socket_path=str(tmp_path / 'control.sock'))


@pytest.fixture
def handler(scroll_config, keybind_manager):
    """A UInputHandler with a mocked virtual device."""
    with patch('huion_keydial_mini.uinput_handler.UInput'):
        h = UInputHandler(scroll_config, keybind_manager)
    h.device.reset_mock()
    return h


class TestEventTypeForKeys:
    def test_scroll_token_is_scroll(self):
        assert event_type_for_keys(['SCROLL_UP']) == BindEventType.SCROLL
        assert event_type_for_keys(['SCROLL_DOWN']) == BindEventType.SCROLL
        assert event_type_for_keys(['SCROLL_LEFT']) == BindEventType.SCROLL
        assert event_type_for_keys(['SCROLL_RIGHT']) == BindEventType.SCROLL

    def test_keyboard_token_is_keyboard(self):
        assert event_type_for_keys(['KEY_F1']) == BindEventType.KEYBOARD
        assert event_type_for_keys(['KEY_LEFTCTRL', 'KEY_C']) == BindEventType.KEYBOARD
        assert event_type_for_keys(['BTN_MIDDLE']) == BindEventType.KEYBOARD

    def test_empty_is_keyboard(self):
        assert event_type_for_keys(None) == BindEventType.KEYBOARD
        assert event_type_for_keys([]) == BindEventType.KEYBOARD

    def test_scroll_actions_set(self):
        assert SCROLL_ACTIONS == {'SCROLL_UP', 'SCROLL_DOWN', 'SCROLL_LEFT', 'SCROLL_RIGHT'}


class TestScrollBindingLoading:
    def test_dial_cw_scroll_is_scroll_type(self, keybind_manager):
        cw = keybind_manager.get_action('DIAL_CW')
        assert cw is not None
        assert cw.type == BindEventType.SCROLL
        assert cw.keys == ['SCROLL_UP']

    def test_dial_ccw_scroll_is_scroll_type(self, keybind_manager):
        ccw = keybind_manager.get_action('DIAL_CCW')
        assert ccw.type == BindEventType.SCROLL
        assert ccw.keys == ['SCROLL_DOWN']

    def test_dial_click_mouse_button_stays_keyboard(self, keybind_manager):
        click = keybind_manager.get_action('DIAL_CLICK')
        assert click.type == BindEventType.KEYBOARD
        assert click.keys == ['BTN_MIDDLE']

    def test_button_scroll_binding_is_scroll_type(self, keybind_manager):
        b2 = keybind_manager.get_action('BUTTON_2')
        assert b2.type == BindEventType.SCROLL

    def test_button_key_binding_stays_keyboard(self, keybind_manager):
        b1 = keybind_manager.get_action('BUTTON_1')
        assert b1.type == BindEventType.KEYBOARD


class TestScrollEmission:
    async def test_dial_cw_emits_wheel_up_on_press(self, handler):
        await handler.send_event(InputEvent(event_type=EventType.KEY_PRESS, key_code='DIAL_CW'))
        handler.device.write.assert_called_once_with(ecodes.EV_REL, ecodes.REL_WHEEL, 1)
        handler.device.syn.assert_called_once()

    async def test_dial_ccw_emits_wheel_down_on_press(self, handler):
        await handler.send_event(InputEvent(event_type=EventType.KEY_PRESS, key_code='DIAL_CCW'))
        handler.device.write.assert_called_once_with(ecodes.EV_REL, ecodes.REL_WHEEL, -1)

    async def test_release_does_not_scroll(self, handler):
        """The dial emits a press+release pair per step; only press should scroll."""
        await handler.send_event(InputEvent(event_type=EventType.KEY_RELEASE, key_code='DIAL_CW'))
        handler.device.write.assert_not_called()

    async def test_button_scroll_emits_on_press(self, handler):
        await handler.send_event(InputEvent(event_type=EventType.KEY_PRESS, key_code='BUTTON_2'))
        handler.device.write.assert_called_once_with(ecodes.EV_REL, ecodes.REL_WHEEL, 1)

    async def test_horizontal_scroll_uses_hwheel(self, scroll_config, tmp_path):
        config = Config({
            'key_mappings': {},
            'dial_settings': {'DIAL_CW': 'SCROLL_RIGHT', 'DIAL_CCW': 'SCROLL_LEFT'},
        })
        km = KeybindManager(config, socket_path=str(tmp_path / 'c.sock'))
        with patch('huion_keydial_mini.uinput_handler.UInput'):
            h = UInputHandler(config, km)
        h.device.reset_mock()

        await h.send_event(InputEvent(event_type=EventType.KEY_PRESS, key_code='DIAL_CW'))
        h.device.write.assert_called_once_with(ecodes.EV_REL, ecodes.REL_HWHEEL, 1)

        h.device.reset_mock()
        await h.send_event(InputEvent(event_type=EventType.KEY_PRESS, key_code='DIAL_CCW'))
        h.device.write.assert_called_once_with(ecodes.EV_REL, ecodes.REL_HWHEEL, -1)
