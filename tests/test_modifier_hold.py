"""Tests for held-modifier behavior in the HID parser.

A button bound exclusively to modifier keys (e.g. KEY_LEFTSHIFT) should be
pressed down when the physical button is pressed and released when it is
released, so it can be *held* while using the mouse, dial, real keyboard, or
other keydial buttons, and stacked with other modifiers.
"""

import pytest

from huion_keydial_mini.config import Config
from huion_keydial_mini.hid_parser import EventType, HIDParser
from huion_keydial_mini.keybind_manager import KeybindManager

# --- HID byte fixtures -------------------------------------------------------
# Type 2 buttons live in the data[0] bitmask; type 1 buttons in bytes 3-5.
B13_SHIFT = bytearray([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])  # type2 bit0
B16_CTRL = bytearray([0x00, 0x00, 0x00, 0x28, 0x00, 0x00, 0x00, 0x00])   # type1 0x28
B1_REGULAR = bytearray([0x00, 0x00, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x00]) # type1 0x0e
B12_CTRL_Z = bytearray([0x00, 0x00, 0x00, 0x19, 0x00, 0x00, 0x00, 0x00]) # type1 0x19
B13_AND_B1 = bytearray([0x01, 0x00, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x00])
B13_AND_B16 = bytearray([0x01, 0x00, 0x00, 0x28, 0x00, 0x00, 0x00, 0x00])
NO_BUTTONS = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


@pytest.fixture
def modifier_config():
    """Config mapping modifier-only buttons plus a regular and a chord button."""
    return Config({
        'key_mappings': {
            'BUTTON_13': 'KEY_LEFTSHIFT',       # held modifier
            'BUTTON_16': 'KEY_LEFTCTRL',        # held modifier
            'BUTTON_1': 'KEY_F1',               # regular tap
            'BUTTON_12': 'KEY_LEFTCTRL+KEY_Z',  # chord -> stays a tap
        },
        'dial_settings': {},
        'debug_mode': True,
    })


@pytest.fixture
def parser(modifier_config, tmp_path):
    """HIDParser wired to a KeybindManager (production-like)."""
    km = KeybindManager(modifier_config, socket_path=str(tmp_path / "control.sock"))
    p = HIDParser(modifier_config)
    p.set_keybind_manager(km)
    return p


def _codes(events):
    return [(e.event_type, e.key_code) for e in events]


class TestHeldModifiers:
    def test_modifier_press_emits_press_immediately(self, parser):
        events = parser.parse(B13_SHIFT)
        assert _codes(events) == [(EventType.KEY_PRESS, 'BUTTON_13')]
        assert parser.held_modifier_buttons == {'BUTTON_13'}

    def test_modifier_release_emits_release(self, parser):
        parser.parse(B13_SHIFT)
        events = parser.parse(NO_BUTTONS)
        assert _codes(events) == [(EventType.KEY_RELEASE, 'BUTTON_13')]
        assert parser.held_modifier_buttons == set()

    def test_regular_tap_fires_while_modifier_held(self, parser):
        # Hold Shift.
        assert _codes(parser.parse(B13_SHIFT)) == [(EventType.KEY_PRESS, 'BUTTON_13')]
        # Press a regular button while Shift is held: no event yet, Shift stays held.
        assert _codes(parser.parse(B13_AND_B1)) == []
        assert parser.held_modifier_buttons == {'BUTTON_13'}
        # Release the regular button (Shift still held): regular tap fires.
        events = parser.parse(B13_SHIFT)
        assert _codes(events) == [
            (EventType.KEY_PRESS, 'BUTTON_1'),
            (EventType.KEY_RELEASE, 'BUTTON_1'),
        ]
        assert parser.held_modifier_buttons == {'BUTTON_13'}
        # Release Shift.
        assert _codes(parser.parse(NO_BUTTONS)) == [(EventType.KEY_RELEASE, 'BUTTON_13')]
        assert parser.held_modifier_buttons == set()

    def test_modifier_stacking(self, parser):
        assert _codes(parser.parse(B13_SHIFT)) == [(EventType.KEY_PRESS, 'BUTTON_13')]
        # Add Ctrl while Shift is held -> only the new modifier presses.
        assert _codes(parser.parse(B13_AND_B16)) == [(EventType.KEY_PRESS, 'BUTTON_16')]
        assert parser.held_modifier_buttons == {'BUTTON_13', 'BUTTON_16'}
        # Release everything -> both modifiers release.
        events = parser.parse(NO_BUTTONS)
        assert _codes(events) == [
            (EventType.KEY_RELEASE, 'BUTTON_13'),
            (EventType.KEY_RELEASE, 'BUTTON_16'),
        ]
        assert parser.held_modifier_buttons == set()

    def test_chord_button_stays_a_tap(self, parser):
        # BUTTON_12 -> Ctrl+Z is not modifier-only, so it must not be held.
        assert _codes(parser.parse(B12_CTRL_Z)) == []
        assert parser.held_modifier_buttons == set()
        events = parser.parse(NO_BUTTONS)
        assert _codes(events) == [
            (EventType.KEY_PRESS, 'BUTTON_12'),
            (EventType.KEY_RELEASE, 'BUTTON_12'),
        ]

    def test_flush_held_modifiers(self, parser):
        parser.parse(B13_SHIFT)
        parser.parse(B13_AND_B16)
        flushed = parser.flush_held_modifiers()
        assert _codes(flushed) == [
            (EventType.KEY_RELEASE, 'BUTTON_13'),
            (EventType.KEY_RELEASE, 'BUTTON_16'),
        ]
        assert parser.held_modifier_buttons == set()

    def test_reset_state_clears_held_modifiers(self, parser):
        parser.parse(B13_SHIFT)
        assert parser.held_modifier_buttons == {'BUTTON_13'}
        parser.reset_state()
        assert parser.held_modifier_buttons == set()
        assert parser.previous_state == {}


class TestHeldModifiersDisabledWithoutManager:
    def test_no_manager_keeps_tap_behavior(self, modifier_config):
        # Without a keybind manager, detection is off: a modifier button behaves
        # like a normal tap (event on release), preserving legacy behavior.
        p = HIDParser(modifier_config)
        assert _codes(p.parse(B13_SHIFT)) == []
        assert p.held_modifier_buttons == set()
        events = p.parse(NO_BUTTONS)
        assert _codes(events) == [
            (EventType.KEY_PRESS, 'BUTTON_13'),
            (EventType.KEY_RELEASE, 'BUTTON_13'),
        ]
