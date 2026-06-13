"""HID data parser for the Huion Keydial Mini."""

import logging
from enum import Enum
from typing import Any, Dict, List, NamedTuple, Optional

from .config import Config

logger = logging.getLogger(__name__)


# Modifier keys that, when a button is bound exclusively to them, cause the
# button to behave as a physically held modifier (pressed on button-down,
# released on button-up) rather than a momentary tap. Lock keys (Caps/Num/
# Scroll) are intentionally excluded because they are toggles, not modifiers.
MODIFIER_KEY_NAMES = frozenset(
    {
        "KEY_LEFTCTRL",
        "KEY_RIGHTCTRL",
        "KEY_LEFTSHIFT",
        "KEY_RIGHTSHIFT",
        "KEY_LEFTALT",
        "KEY_RIGHTALT",
        "KEY_LEFTMETA",
        "KEY_RIGHTMETA",
    }
)


class EventType(Enum):
    """Types of input events."""

    KEY_PRESS = "key_press"
    KEY_RELEASE = "key_release"
    DIAL_ROTATE = "dial_rotate"
    DIAL_CLICK = "dial_click"


class InputEvent(NamedTuple):
    """Represents an input event."""

    event_type: EventType
    key_code: Optional[str] = None
    direction: Optional[int] = (
        None  # For dial rotation: 1 = clockwise, -1 = counterclockwise
    )
    value: Optional[int] = None
    raw_data: Optional[bytearray] = None  # Store raw data for debugging


class HIDParser:
    """Parser for HID data from the Huion Keydial Mini."""

    def __init__(self, config: Config):
        self.config = config
        self.previous_state = {}
        self.report_formats = {}  # Cache discovered report formats
        self.debug_mode = getattr(config, "debug_mode", False)

        # Combo detection state
        self.peak_buttons_this_session = (
            set()
        )  # Track peak button set for combo detection
        self.key_event_triggered = False  # Flag to prevent multiple actions per session

        # Sticky state tracking
        self.active_sticky_buttons = (
            set()
        )  # Track which buttons have active sticky bindings
        self.active_sticky_actions = {}  # Track action_id -> buttons for active sticky actions
        self.keybind_manager = None  # Will be set by the main application

        # Held-modifier state: buttons bound exclusively to modifier keys are
        # held down for as long as the physical button is held.
        self.held_modifier_buttons = set()

    def parse(
        self, data: bytearray, characteristic_uuid: Optional[str] = None
    ) -> List[InputEvent]:
        """Parse HID data and return input events."""
        events = []

        try:
            # Log raw data for debugging
            if self.debug_mode:
                logger.debug(
                    f"Parsing HID data: {data.hex()} (length: {len(data)}) from characteristic: {characteristic_uuid}"
                )

            if len(data) < 1:
                logger.warning("Received empty HID report")
                return events

            # Parse based on data format rather than characteristic UUID
            # The device is using standard HID over GATT, so we need to parse the data directly

            # Try to parse as dial events first (f100/f103 format)
            dial_events = self._parse_dial_events(data)
            if dial_events:
                events.extend(dial_events)
                return events

            # Try to parse as button events (button ID format)
            button_events = self._parse_button_events(data)
            if button_events:
                events.extend(button_events)
                return events

        except Exception as e:
            logger.error(f"Error parsing HID data: {e}")
            if self.debug_mode:
                import traceback

                logger.debug(traceback.format_exc())

        return events

    def set_keybind_manager(self, keybind_manager):
        """Set the keybind manager for sticky binding detection."""
        self.keybind_manager = keybind_manager

    def _is_sticky_binding(self, action_id: str) -> bool:
        """Check if a binding is sticky."""
        if not self.keybind_manager:
            return False
        action = self.keybind_manager.get_action(action_id)
        return action and action.sticky if action else False

    def _extract_handle_from_uuid(self, uuid: str) -> str:
        """Extract handle from characteristic UUID."""
        # UUID format: "0000001f-0000-1000-8000-00805f9b34fb"
        # Extract the handle part (last 2 digits before the first dash)
        parts = uuid.split("-")
        if parts and len(parts[0]) >= 8:
            return parts[0][-2:]  # Last 2 characters
        return ""

    def _parse_button_events(self, data: bytearray) -> List[InputEvent]:
        """Parse button events, bracketing regular handling with held modifiers.

        Buttons bound exclusively to modifier keys are emitted as real
        press/release events that wrap the regular button handling, so they
        behave as physically held modifiers (Shift+drag, Ctrl+X across two
        buttons, modifier stacking, ...). All other buttons keep their existing
        momentary/combo/sticky behavior.
        """
        events = []

        if len(data) < 8:
            return events

        # Validate that this is actually button data (not dial data)
        if data[0] == 0xF1:
            return events

        all_current_buttons = set(self._get_button_names_from_data(data))
        current_modifier_buttons = {
            button for button in all_current_buttons if self._is_modifier_button(button)
        }
        current_regular_buttons = all_current_buttons - current_modifier_buttons

        # 1. Press newly-held modifier buttons FIRST so they wrap regular taps.
        for button in sorted(current_modifier_buttons - self.held_modifier_buttons):
            events.append(
                InputEvent(
                    event_type=EventType.KEY_PRESS, key_code=button, raw_data=data
                )
            )
            self.held_modifier_buttons.add(button)
            logger.debug(f"Modifier held: {button}")

        # 2. Handle regular (non-modifier) buttons with the existing logic.
        events.extend(self._parse_regular_button_events(current_regular_buttons, data))

        # 3. Release modifier buttons that are no longer held, LAST.
        for button in sorted(self.held_modifier_buttons - current_modifier_buttons):
            events.append(
                InputEvent(
                    event_type=EventType.KEY_RELEASE, key_code=button, raw_data=data
                )
            )
            self.held_modifier_buttons.discard(button)
            logger.debug(f"Modifier released: {button}")

        return events

    def _is_modifier_button(self, button: str) -> bool:
        """Return True if a button is bound exclusively to modifier keys.

        Such buttons are treated as physically held modifiers. Requires a
        keybind manager (absent in unit tests), so behavior is unchanged when no
        manager is set.
        """
        if not self.keybind_manager:
            return False
        action = self.keybind_manager.get_action(button)
        if not action or not action.keys:
            return False
        return all(key in MODIFIER_KEY_NAMES for key in action.keys)

    def _parse_regular_button_events(
        self, current_button_names: set, data: bytearray
    ) -> List[InputEvent]:
        """Parse non-modifier button events (individual/combo detection + sticky)."""
        events = []

        # current_button_names is supplied already filtered of modifier buttons.
        previous_button_names = set(self.previous_state.get("button_names", []))

        # Find pressed and released buttons
        pressed_buttons = current_button_names - previous_button_names
        released_buttons = previous_button_names - current_button_names

        # Handle button presses - update session state
        if pressed_buttons:
            # Any new button press resets the event trigger flag
            self.key_event_triggered = False

            # Update peak button set if needed
            if current_button_names != self.peak_buttons_this_session:
                self.peak_buttons_this_session = current_button_names.copy()

        # Handle button releases - this is where all actions are triggered
        if released_buttons and not self.key_event_triggered:
            # First, handle any active sticky action releases
            sticky_released = False
            for action_id, action_buttons in list(self.active_sticky_actions.items()):
                # Check if any buttons from this sticky action are being released
                if released_buttons & action_buttons:
                    # Generate release event for this sticky action
                    events.append(
                        InputEvent(
                            event_type=EventType.KEY_RELEASE,
                            key_code=action_id,
                            raw_data=data,
                        )
                    )
                    logger.debug(f"Sticky action released: {action_id}")

                    # Remove released buttons from tracking
                    remaining_buttons = action_buttons - released_buttons
                    if remaining_buttons:
                        # Some buttons still pressed for this action
                        self.active_sticky_actions[action_id] = remaining_buttons
                        # Update active_sticky_buttons to reflect what's still active
                        for button in released_buttons:
                            if button in self.active_sticky_buttons:
                                self.active_sticky_buttons.remove(button)
                    else:
                        # All buttons for this action released
                        del self.active_sticky_actions[action_id]
                        # Remove all buttons for this action from active tracking
                        for button in action_buttons:
                            if button in self.active_sticky_buttons:
                                self.active_sticky_buttons.remove(button)

                    sticky_released = True
                    self.key_event_triggered = True

            # Handle regular (non-sticky) action if no sticky action was released
            if not sticky_released:
                # Generate action ID from peak button set
                action_id = self._generate_combo_id(self.peak_buttons_this_session)

                if (
                    action_id
                    and self._should_check_combo_mapping(action_id)
                    and not self._is_sticky_binding(action_id)
                ):
                    # Handle non-sticky binding (momentary action on release)
                    if (
                        not self.active_sticky_buttons
                    ):  # Only if no sticky buttons are active
                        events.append(
                            InputEvent(
                                event_type=EventType.KEY_PRESS,
                                key_code=action_id,
                                raw_data=data,
                            )
                        )
                        events.append(
                            InputEvent(
                                event_type=EventType.KEY_RELEASE,
                                key_code=action_id,
                                raw_data=data,
                            )
                        )
                        logger.debug(f"Action triggered: {action_id}")
                        self.key_event_triggered = True
                    else:
                        logger.debug(
                            f"Blocking action {action_id} due to active sticky bindings"
                        )

        # Handle sticky button presses (generate press events when buttons are first pressed)
        if pressed_buttons:
            # Check if the current action (from current button state) is sticky
            current_action_id = self._generate_combo_id(current_button_names)
            if current_action_id and self._is_sticky_binding(current_action_id):
                # Only activate if no sticky actions are currently active
                if not self.active_sticky_actions:
                    # Generate press event for sticky action
                    events.append(
                        InputEvent(
                            event_type=EventType.KEY_PRESS,
                            key_code=current_action_id,
                            raw_data=data,
                        )
                    )
                    # Track this sticky action and its buttons
                    self.active_sticky_actions[current_action_id] = (
                        current_button_names.copy()
                    )
                    # Track which individual buttons are part of sticky actions
                    for button in current_button_names:
                        self.active_sticky_buttons.add(button)
                    logger.debug(f"Sticky action pressed: {current_action_id}")
                else:
                    logger.debug(
                        f"Blocking sticky action {current_action_id} - sticky action already active"
                    )

        # Reset session when all buttons are released
        if len(current_button_names) == 0:
            self.peak_buttons_this_session = set()
            self.active_sticky_buttons = set()
            self.active_sticky_actions = {}
            if not events:
                self.key_event_triggered = False

        # Update state
        self.previous_state["button_names"] = list(current_button_names)

        return events

    def _generate_combo_id(self, buttons: set) -> str:
        """Generate a standardized combo ID from a set of buttons."""
        if not buttons:
            return ""

        # Sort buttons to ensure consistent combo IDs regardless of order
        sorted_buttons = sorted(list(buttons))
        combo_id = "+".join(sorted_buttons)
        return combo_id

    def _should_check_combo_mapping(self, combo_id: str) -> bool:
        """Determine if we should check for a combo mapping."""
        if not combo_id:
            return False

        # Always generate events for valid combo IDs and let UInputHandler handle mapping lookup
        # This is because keydialctl mappings are stored in KeybindManager, not config.key_mappings
        return True

    def _get_button_names_from_data(self, data: bytearray) -> List[str]:
        """Get button names from data"""
        button_names = []
        # There are 2 types of button signals going on
        # First we'll handle type 1. Type 1 button combo signals start at the 4th byte,
        # and signal up to 3 buttons in 3 bytes. Order is not preserved.
        # Some 4 button combos are possible, but not all so we'll just use the first 3.
        type1_button_mappings = {
            0x0E: "BUTTON_1",
            0x0A: "BUTTON_2",
            0x0F: "BUTTON_3",
            0x4C: "BUTTON_4",
            0x0C: "BUTTON_5",
            0x07: "BUTTON_6",
            0x05: "BUTTON_7",
            0x08: "BUTTON_8",
            0x16: "BUTTON_9",
            0x1D: "BUTTON_10",
            0x06: "BUTTON_11",
            0x19: "BUTTON_12",
            0x28: "BUTTON_16",
            0x2C: "BUTTON_17",
            0x11: "BUTTON_18",
        }

        for i in range(3, 6):
            button_name = type1_button_mappings.get(data[i])
            if button_name:
                button_names.append(button_name)

        # Now for type 2. Type 2 button combo signals use only the first byte using bitmasking.
        # The bits are:
        # button 13: bit 0
        # button 14: bit 2
        # button 15: bit 1
        type2_button_mappings = {
            0x01: "BUTTON_13",
            0x04: "BUTTON_14",
            0x02: "BUTTON_15",
        }
        for key, value in type2_button_mappings.items():
            if data[0] & key:
                button_names.append(value)

        return button_names

    def _parse_dial_events(self, data: bytearray) -> List[InputEvent]:
        """Parse dial rotation and click events.

        Handles the real device wire formats as well as the legacy 0xf1
        format kept for backward compatibility and unit tests:
        - Click  (real): 2-byte report ``XX 00``; ``data[0] != 0`` means pressed.
        - Rotate (real): 6-byte report ``00 00 00 00 00 DD`` where ``DD`` is a
          signed per-report step delta (0x01 = +1, 0xff = -1, 0x00 = idle).
        - Legacy: 9-byte ``0xf1[clicked][count][direction]...`` report.
        """
        # Real device dial click: 2-byte report, data[0] != 0 means pressed.
        if len(data) == 2:
            return self._make_dial_click_events(data[0] != 0x00, data)

        # Real device dial rotation: 6-byte report led by 0x00 with a signed
        # step delta in the final byte. Requiring data[0] == 0x00 rejects the
        # 6-byte vendor report (06 d1 63 5a 00 00) that shares this length.
        if len(data) == 6 and data[0] == 0x00:
            delta = data[5] - 256 if data[5] >= 0x80 else data[5]
            if delta == 0:
                return []
            if delta > 0:
                return self._make_dial_rotation_events("DIAL_CW", 1, delta, data)
            return self._make_dial_rotation_events("DIAL_CCW", -1, -delta, data)

        # Legacy 0xf1 dial format (9 bytes).
        if len(data) >= 8 and data[0] == 0xF1:
            return self._parse_legacy_dial_events(data)

        return []

    def _parse_legacy_dial_events(self, data: bytearray) -> List[InputEvent]:
        """Parse the legacy 9-byte 0xf1 dial format (older captures and tests)."""
        # Dial click: f1[clicked]00...  (data[2] == 0x00 distinguishes a click)
        if data[2] == 0x00:
            return self._make_dial_click_events(data[1] == 0x03, data)

        # Dial rotation: f100[count][direction]...
        count = data[2]
        direction_byte = data[3]
        if direction_byte == 0x00:
            return self._make_dial_rotation_events("DIAL_CW", 1, count, data)
        elif direction_byte == 0xFF:
            movement = 256 - count if count > 0 else 0
            return self._make_dial_rotation_events("DIAL_CCW", -1, movement, data)
        return []

    def _make_dial_click_events(
        self, pressed: bool, data: bytearray
    ) -> List[InputEvent]:
        """Build dial-click press/release events with edge detection."""
        events = []
        if pressed and not self.previous_state.get("dial_clicked", False):
            events.append(
                InputEvent(
                    event_type=EventType.KEY_PRESS, key_code="DIAL_CLICK", raw_data=data
                )
            )
            self.previous_state["dial_clicked"] = True
        elif not pressed and self.previous_state.get("dial_clicked", False):
            events.append(
                InputEvent(
                    event_type=EventType.KEY_RELEASE,
                    key_code="DIAL_CLICK",
                    raw_data=data,
                )
            )
            self.previous_state["dial_clicked"] = False
        return events

    def _make_dial_rotation_events(
        self, key_code: str, direction: int, movement: int, data: bytearray
    ) -> List[InputEvent]:
        """Build dial rotation press/release event pairs scaled by sensitivity."""
        events = []
        sensitivity = self.config.dial_settings.get("sensitivity", 1.0)
        steps = max(1, int(movement * sensitivity))
        for step_num in range(1, steps + 1):
            events.append(
                InputEvent(
                    event_type=EventType.KEY_PRESS,
                    key_code=key_code,
                    direction=direction,
                    value=step_num,
                    raw_data=data,
                )
            )
            events.append(
                InputEvent(
                    event_type=EventType.KEY_RELEASE,
                    key_code=key_code,
                    direction=direction,
                    value=step_num,
                    raw_data=data,
                )
            )
        return events

    def reset_state(self):
        """Reset the parser state."""
        self.previous_state = {}
        self.held_modifier_buttons = set()
        logger.debug("Parser state reset")

    def flush_held_modifiers(self) -> List[InputEvent]:
        """Emit release events for all held modifier buttons and clear them.

        Used as a stuck-key safeguard when the device disconnects or the driver
        stops while a modifier button is still physically held.
        """
        held = sorted(self.held_modifier_buttons)
        events = [
            InputEvent(event_type=EventType.KEY_RELEASE, key_code=button, raw_data=None)
            for button in held
        ]
        if held:
            logger.debug(f"Flushing held modifiers: {held}")
        self.held_modifier_buttons = set()
        return events

    def get_debug_info(self) -> Dict[str, Any]:
        """Get debug information about the parser state."""
        return {
            "previous_state": self.previous_state,
            "report_formats": self.report_formats,
            "debug_mode": self.debug_mode,
        }
