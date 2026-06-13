#!/usr/bin/env python3
"""Keybind manager for Huion Keydial Mini with runtime control via Unix socket."""

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .notification import notify

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events that can be bound."""
    KEYBOARD = "keyboard"
    SCROLL = "scroll"


# Scroll action tokens that map to mouse wheel movement instead of key presses.
SCROLL_ACTIONS = frozenset({
    'SCROLL_UP', 'SCROLL_DOWN', 'SCROLL_LEFT', 'SCROLL_RIGHT',
})


def event_type_for_keys(keys: Optional[List[str]]) -> EventType:
    """Determine the action type for a list of target keys.

    Returns SCROLL when every token is a scroll action (e.g. SCROLL_UP),
    otherwise KEYBOARD.
    """
    if keys and all(key in SCROLL_ACTIONS for key in keys):
        return EventType.SCROLL
    return EventType.KEYBOARD


@dataclass
class KeybindAction:
    """Represents a keybind action."""
    type: EventType
    keys: Optional[List[str]] = None
    description: Optional[str] = None
    sticky: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'type': self.type.value,
            'keys': self.keys,
            'description': self.description,
            'sticky': self.sticky
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KeybindAction':
        """Create from dictionary."""
        return cls(
            type=EventType(data['type']),
            keys=data.get('keys'),
            description=data.get('description'),
            sticky=data.get('sticky', False)
        )


class KeybindManager:
    """Manages in-memory keybind mappings with Unix socket control interface."""

    def __init__(self, config: Config, socket_path: Optional[str] = None):
        self.config = config
        self.socket_path = socket_path or self._get_default_socket_path()
        self.layers: list = []
        self.layers_inherited: list = []
        self.layer_names: list = []
        self.current_layer: int = 0
        self.server: Optional[asyncio.Server] = None
        self._load_layers()

    @property
    def keybind_map(self) -> Dict[str, KeybindAction]:
        """Return the current layer's keybind map with inheritance applied."""
        if self.layers_inherited and self.current_layer < len(self.layers_inherited):
            return self.layers_inherited[self.current_layer]
        return {}

    def _get_default_socket_path(self) -> str:
        """Get default socket path for user-level service."""
        socket_dir = Path.home() / ".local" / "share" / "huion-keydial-mini"
        socket_dir.mkdir(parents=True, exist_ok=True)
        return str(socket_dir / "control.sock")

    def _load_layers(self):
        """Load layers from config. Falls back to single-layer mode if no layers defined."""
        if self.config is None:
            self.layers = [{}]
            self.layer_names = ["Default"]
            self.current_layer = 0
            logger.info("No config — single-layer fallback mode")
            return

        raw_layers = self.config.layers

        def build_keybind_map(layer_data: Dict[str, Any]) -> Dict[str, KeybindAction]:
            """Build a keybind_map from a single layer's config data."""
            km = {}

            def handle_key_mapping(mappings: Dict[str, str], sticky: bool = False):
                for action_id, key in mappings.items():
                    if not isinstance(action_id, str):
                        logger.warning(f"Config: Action ID must be a string, ignoring: {action_id}")
                        continue
                    if not isinstance(key, str) or not key:
                        logger.warning(
                            f"Config: Key mapping must be a non-empty string, ignoring: {action_id} -> {key}"
                        )
                        continue

                    normalized_action_id = self._validate_and_normalize_action_id(action_id)
                    if normalized_action_id:
                        keys = [k.strip() for k in key.split('+')]
                        km[normalized_action_id] = KeybindAction(
                            type=event_type_for_keys(keys),
                            keys=keys,
                            description=f"{normalized_action_id} -> {key}",
                            sticky=sticky
                        )

            handle_key_mapping(layer_data.get('key_mappings', {}))
            handle_key_mapping(layer_data.get('sticky_key_mappings', {}), sticky=True)

            dial_settings = layer_data.get('dial_settings', {})
            for dial_key in ['DIAL_CW', 'DIAL_CCW', 'DIAL_CLICK']:
                if dial_settings.get(dial_key):
                    km[dial_key] = KeybindAction(
                        type=event_type_for_keys([dial_settings[dial_key]]),
                        keys=[dial_settings[dial_key]],
                        description=f"{dial_key} -> {dial_settings[dial_key]}"
                    )

            return km

        if raw_layers and len(raw_layers) > 0:
            self.layers = []
            self.layer_names = []
            for layer_data in raw_layers:
                self.layers.append(build_keybind_map(layer_data))
                self.layer_names.append(layer_data.get('name', f"Layer {len(self.layers)}"))
            self.current_layer = 0
            self.layers_inherited = []
            for i, layer in enumerate(self.layers):
                inherited_layer = dict(layer)
                if i > 0:
                    for action_id, action in self.layers_inherited[i-1].items():
                        if action_id not in inherited_layer:
                            inherited_layer[action_id] = action
                self.layers_inherited.append(inherited_layer)
                if i > 0:
                    inherited_count = sum(1 for aid in self.layers_inherited[i-1] if aid not in self.layers[i])
                    if inherited_count:
                        logger.info(
                            f"Layer '{self.layer_names[i]}' inherited {inherited_count} "
                            f"binding(s) from '{self.layer_names[i-1]}'"
                        )
            logger.info(f"Loaded {len(self.layers)} layers: {self.layer_names}")
        else:
            self.layers = [build_keybind_map({
                'key_mappings': self.config.key_mappings,
                'sticky_key_mappings': self.config.sticky_key_mappings,
                'dial_settings': self.config.dial_settings,
            })]
            self.layers_inherited = [dict(self.layers[0])]
            self.layer_names = ["Default"]
            self.current_layer = 0
            logger.info("No layers configured — single-layer fallback mode")

    def _validate_and_normalize_action_id(self, action_id: str) -> Optional[str]:
        """Validate and normalize an action ID from config file."""
        valid_buttons = [
            'BUTTON_1', 'BUTTON_2', 'BUTTON_3', 'BUTTON_4',
            'BUTTON_5', 'BUTTON_6', 'BUTTON_7', 'BUTTON_8',
            'BUTTON_9', 'BUTTON_10', 'BUTTON_11', 'BUTTON_12',
            'BUTTON_13', 'BUTTON_14', 'BUTTON_15', 'BUTTON_16',
            'BUTTON_17', 'BUTTON_18'
        ]
        valid_dial_actions = ['DIAL_CW', 'DIAL_CCW', 'DIAL_CLICK']

        # Check if it's a valid action_id
        if action_id in valid_dial_actions:
            # Valid dial action
            return action_id
        elif action_id in valid_buttons:
            # Valid individual button
            return action_id
        elif '+' in action_id:
            # Check if it's a valid combo
            combo_buttons = [b.strip() for b in action_id.split('+')]

            if len(combo_buttons) < 2:
                logger.warning(f"Config: Button combinations must include at least 2 buttons, ignoring: {action_id}")
                return None

            # Check for duplicate buttons
            if len(combo_buttons) != len(set(combo_buttons)):
                logger.warning(f"Config: Button combinations cannot contain duplicate buttons, ignoring: {action_id}")
                return None

            for button in combo_buttons:
                if button not in valid_buttons:
                    logger.warning(f"Config: Invalid button name '{button}' in combination '{action_id}', ignoring")
                    return None

            # Normalize combo format (sorted for consistency)
            sorted_buttons = sorted(combo_buttons)
            return "+".join(sorted_buttons)
        else:
            logger.warning(f"Config: Invalid action ID '{action_id}', ignoring")
            return None

    async def start_socket_server(self):
        """Start the Unix socket server for control interface."""
        try:
            # Remove existing socket file if it exists
            socket_path = Path(self.socket_path)
            if socket_path.exists():
                socket_path.unlink()

            self.server = await asyncio.start_unix_server(
                self._handle_client,
                path=self.socket_path
            )

            logger.info(f"Started control socket server at {self.socket_path}")

        except Exception as e:
            logger.error(f"Failed to start socket server: {e}")
            raise

    async def stop_socket_server(self):
        """Stop the Unix socket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()

            # Remove socket file
            socket_path = Path(self.socket_path)
            if socket_path.exists():
                socket_path.unlink()

            logger.info("Stopped control socket server")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle client connection to the control socket."""
        try:
            # Read command
            data = await reader.read(1024)
            if not data:
                return

            command = json.loads(data.decode('utf-8'))
            response = await self._process_command(command)

            # Send response with newline delimiter
            writer.write((json.dumps(response) + '\n').encode('utf-8'))
            await writer.drain()

        except json.JSONDecodeError:
            error_response = {'status': 'error', 'message': 'Invalid JSON'}
            writer.write((json.dumps(error_response) + '\n').encode('utf-8'))
            await writer.drain()
        except Exception as e:
            logger.error(f"Error handling client command: {e}")
            error_response = {'status': 'error', 'message': str(e)}
            writer.write((json.dumps(error_response) + '\n').encode('utf-8'))
            await writer.drain()
        # Don't close the connection here - let the client close it

    async def _process_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Process a control command."""
        cmd_type = command.get('command')

        try:
            if cmd_type == 'get_bindings':
                return await self._cmd_get_bindings()
            elif cmd_type == 'set_binding':
                return await self._cmd_set_binding(command)
            elif cmd_type == 'remove_binding':
                return await self._cmd_remove_binding(command)
            elif cmd_type == 'clear_all':
                return await self._cmd_clear_all()
            elif cmd_type == 'list_actions':
                return await self._cmd_list_actions()
            elif cmd_type == 'get_layer':
                return await self._cmd_get_layer()
            elif cmd_type == 'set_layer':
                return await self._cmd_set_layer(command)
            else:
                return {'status': 'error', 'message': f'Unknown command: {cmd_type}'}
        except Exception as e:
            logger.error(f"Error processing command {cmd_type}: {e}")
            return {'status': 'error', 'message': str(e)}

    async def _cmd_get_bindings(self) -> Dict[str, Any]:
        """Get all current keybindings from the active layer."""
        bindings = {}
        for action_id, action in self.get_all_actions().items():
            bindings[action_id] = action.to_dict()

        return {
            'status': 'success',
            'bindings': bindings,
            'layer_index': self.current_layer,
            'layer_name': self.get_current_layer_name(),
        }

    async def _cmd_set_binding(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Set a keybinding."""
        action_id = command.get('action_id')
        action_data = command.get('action')

        if not action_id or not action_data:
            return {'status': 'error', 'message': 'Missing action_id or action'}

        try:
            action = KeybindAction.from_dict(action_data)
            self.keybind_map[action_id] = action

            logger.info(f"Set binding {action_id}: {action.description}")
            return {
                'status': 'success',
                'message': f'Binding {action_id} updated'
            }
        except Exception as e:
            return {'status': 'error', 'message': f'Invalid action data: {e}'}

    async def _cmd_remove_binding(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a keybinding."""
        action_id = command.get('action_id')

        if not action_id:
            return {'status': 'error', 'message': 'Missing action_id'}

        if action_id in self.keybind_map:
            del self.keybind_map[action_id]
            logger.info(f"Removed binding {action_id}")
            return {
                'status': 'success',
                'message': f'Binding {action_id} removed'
            }
        else:
            return {
                'status': 'error',
                'message': f'Binding {action_id} not found'
            }

    async def _cmd_clear_all(self) -> Dict[str, Any]:
        """Clear all keybindings in the current layer."""
        if self.layers:
            count = len(self.layers[self.current_layer])
            self.layers[self.current_layer].clear()
            self.layers_inherited[self.current_layer] = dict(self.layers[self.current_layer])
            if self.current_layer > 0:
                for action_id, action in self.layers_inherited[self.current_layer - 1].items():
                    if action_id not in self.layers_inherited[self.current_layer]:
                        self.layers_inherited[self.current_layer][action_id] = action
            logger.info(f"Cleared all {count} bindings in layer {self.current_layer}")
        else:
            count = 0
        return {
            'status': 'success',
            'message': f'Cleared {count} bindings'
        }

    async def _cmd_list_actions(self) -> Dict[str, Any]:
        """List available action IDs in the current layer."""
        return {
            'status': 'success',
            'actions': list(self.get_all_actions().keys())
        }

    async def _cmd_get_layer(self) -> Dict[str, Any]:
        """Get current layer info."""
        return {
            'status': 'success',
            'layer_index': self.current_layer,
            'layer_name': self.get_current_layer_name(),
            'layer_count': self.get_layer_count(),
        }

    async def _cmd_set_layer(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Switch to a specific layer or cycle to next."""
        mode = command.get('mode', 'next')

        if mode == 'next':
            self.next_layer()
            return {
                'status': 'success',
                'layer_index': self.current_layer,
                'layer_name': self.get_current_layer_name(),
                'message': f'Switched to {self.get_current_layer_name()}'
            }
        else:
            index = command.get('index')
            if index is None:
                return {'status': 'error', 'message': 'Missing layer index'}
            try:
                index = int(index)
            except (TypeError, ValueError):
                return {'status': 'error', 'message': f'Invalid layer index: {index}'}

            if 0 <= index < self.get_layer_count():
                self.set_layer(index)
                return {
                    'status': 'success',
                    'layer_index': self.current_layer,
                    'layer_name': self.get_current_layer_name(),
                    'message': f'Switched to {self.get_current_layer_name()}'
                }
            else:
                return {
                    'status': 'error',
                    'message': f'Layer index {index} out of range (0-{self.get_layer_count() - 1})',
                }

    def get_action(self, action_id: str) -> Optional[KeybindAction]:
        """Get a keybind action by ID from the current layer (with inheritance)."""
        if not self.layers_inherited:
            return None
        return self.layers_inherited[self.current_layer].get(action_id)

    def set_action(self, action_id: str, action: KeybindAction):
        """Set a keybind action in the current layer (updates both original and inherited views).

        Changes cascade upward: any higher layer that inherited action_id from this layer (rather
        than defining it explicitly) is updated to the new value.
        """
        if self.layers:
            self.layers[self.current_layer][action_id] = action
            self.layers_inherited[self.current_layer][action_id] = action
            # Propagate to higher layers that inherited this binding from the current layer.
            for m in range(self.current_layer + 1, len(self.layers)):
                if action_id not in self.layers[m]:
                    self.layers_inherited[m][action_id] = action
                else:
                    break  # Layer m overrides the binding; layers above it are unaffected.
            logger.info(f"Set binding {action_id}: {action.description}")

    def remove_action(self, action_id: str) -> bool:
        """Remove a keybind action from the current layer (from both original and inherited views).

        Removal cascades upward: any higher layer that inherited action_id from this layer has its
        inherited view updated to whatever the next lower layer now provides (or removed entirely if
        nothing provides it below).
        """
        removed = False
        if self.layers and action_id in self.layers[self.current_layer]:
            del self.layers[self.current_layer][action_id]
            removed = True
        if self.layers_inherited and action_id in self.layers_inherited[self.current_layer]:
            del self.layers_inherited[self.current_layer][action_id]
            removed = True
        if removed:
            # Propagate removal to higher layers that inherited from this one.
            for m in range(self.current_layer + 1, len(self.layers)):
                if action_id not in self.layers[m]:
                    # Re-resolve from the layer immediately below m (which may have changed).
                    below = self.layers_inherited[m - 1].get(action_id)
                    if below is not None:
                        self.layers_inherited[m][action_id] = below
                    else:
                        self.layers_inherited[m].pop(action_id, None)
                else:
                    break  # Layer m overrides the binding; layers above it are unaffected.
            logger.info(f"Removed binding {action_id}")
        return removed

    def get_all_actions(self) -> Dict[str, KeybindAction]:
        """Get all keybind actions in the current layer (with inheritance)."""
        if not self.layers_inherited:
            return {}
        return self.layers_inherited[self.current_layer].copy()

    def has_combo_mapping(self, combo_id: str) -> bool:
        """Check if a combo mapping exists in the current layer (with inheritance)."""
        if not self.layers_inherited:
            return False
        return combo_id in self.layers_inherited[self.current_layer]

    def is_combo_action(self, action_id: str) -> bool:
        """Check if an action ID represents a combo (contains '+')."""
        return '+' in action_id

    def set_combo_action(self, buttons: List[str], keys: List[str], description: Optional[str] = None):
        """Set a combo action from a list of buttons and target keys in the current layer."""
        sorted_buttons = sorted(buttons)
        combo_id = "+".join(sorted_buttons)

        action = KeybindAction(
            type=EventType.KEYBOARD,
            keys=keys,
            description=description or f"Combo {combo_id} -> {'+'.join(keys)}"
        )

        self.set_action(combo_id, action)
        return combo_id

    def get_combo_mappings(self) -> Dict[str, KeybindAction]:
        """Get all combo mappings (action IDs containing '+') in the current layer (with inheritance)."""
        if not self.layers_inherited:
            return {}
        return {
            action_id: action
            for action_id, action in self.layers_inherited[self.current_layer].items()
            if self.is_combo_action(action_id)
        }

    def get_individual_mappings(self) -> Dict[str, KeybindAction]:
        """Get all individual button mappings (action IDs not containing '+') in the current layer (with inheritance).
        """
        if not self.layers_inherited:
            return {}
        return {
            action_id: action
            for action_id, action in self.layers_inherited[self.current_layer].items()
            if not self.is_combo_action(action_id)
        }

    def set_layer(self, index: int):
        """Switch to a specific layer (0 to num_layers-1)."""
        if not self.layers:
            return
        if 0 <= index < len(self.layers):
            self.current_layer = index
            name = self.layer_names[index] if index < len(self.layer_names) else f"Layer {index}"
            logger.info(f"Switched to layer {index}: {name}")
            notify("Layer Changed", f"Switched to {name}", "dialog-information")
        else:
            logger.warning(f"Invalid layer index {index}, must be 0-{len(self.layers) - 1}")

    def next_layer(self):
        """Cycle to the next layer (wraps around)."""
        if not self.layers:
            return
        self.current_layer = (self.current_layer + 1) % len(self.layers)
        if self.current_layer < len(self.layer_names):
            name = self.layer_names[self.current_layer]
        else:
            name = f"Layer {self.current_layer}"
        logger.info(f"Switched to layer {self.current_layer}: {name}")
        notify("Layer Changed", f"Switched to {name}", "dialog-information")

    def get_current_layer_name(self) -> str:
        """Get the name of the current layer."""
        if not self.layers or self.current_layer >= len(self.layer_names):
            return "Unknown"
        return self.layer_names[self.current_layer]

    def get_layer_count(self) -> int:
        """Get the number of layers."""
        return len(self.layers)


# Client-side functions for keydialctl
async def send_command(socket_path: str, command: Dict[str, Any]) -> Dict[str, Any]:
    """Send a command to the keybind manager via Unix socket."""
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # Send command
        writer.write(json.dumps(command).encode('utf-8'))
        await writer.drain()

        # Read response (until newline delimiter)
        data = await reader.readline()
        if not data:
            return {'status': 'error', 'message': 'No response from service'}

        response = json.loads(data.decode('utf-8'))

        writer.close()
        await writer.wait_closed()

        return response

    except FileNotFoundError:
        return {'status': 'error', 'message': 'Service not running (socket not found)'}
    except ConnectionRefusedError:
        return {'status': 'error', 'message': 'Service not running (connection refused)'}
    except json.JSONDecodeError as e:
        return {'status': 'error', 'message': f'Invalid response from service: {e}'}
    except Exception as e:
        return {'status': 'error', 'message': f'Communication error: {e}'}
