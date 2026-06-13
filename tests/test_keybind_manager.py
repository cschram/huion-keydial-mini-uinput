"""Tests for the keybind manager."""

import pytest

from huion_keydial_mini.config import Config
from huion_keydial_mini.keybind_manager import KeybindManager


class TestKeybindManager:
    """Tests for the keybind manager."""

    @pytest.fixture
    def keybind_manager(self):
        """Create a keybind manager instance."""
        return KeybindManager(config=Config({
            'key_mappings': {
                'BUTTON_1': 'KEY_F1',
            },
            'sticky_key_mappings': {
                'BUTTON_2': 'KEY_F2',
            },
        }))

    @pytest.mark.keybind_manager
    def test_keybind_manager_initialization(self, keybind_manager):
        """Test the keybind manager initialization."""
        assert keybind_manager is not None

    @pytest.mark.keybind_manager
    def test_keybind_manager_load_initial_bindings(self, keybind_manager: KeybindManager):
        """Test the keybind manager load initial bindings."""
        assert keybind_manager.keybind_map is not None
        assert len(keybind_manager.keybind_map) == 2
        assert keybind_manager.keybind_map['BUTTON_1'].keys == ['KEY_F1']
        assert keybind_manager.keybind_map['BUTTON_2'].keys == ['KEY_F2']
        assert keybind_manager.keybind_map['BUTTON_1'].sticky is False
        assert keybind_manager.keybind_map['BUTTON_2'].sticky is True

    @pytest.mark.keybind_manager
    def test_layer_inheritance(self):
        """Test that layers inherit bindings from the layer below them."""
        config = Config({
            'layers': [
                {
                    'name': 'Base',
                    'key_mappings': {
                        'BUTTON_1': 'KEY_A',
                        'BUTTON_2': 'KEY_B',
                    },
                    'dial_settings': {
                        'DIAL_CW': 'SCROLL_UP',
                        'DIAL_CLICK': 'LAYER_NEXT',
                    },
                },
                {
                    'name': 'Child',
                    'key_mappings': {
                        'BUTTON_2': 'KEY_C',
                    },
                    'dial_settings': {
                        'DIAL_CLICK': 'LAYER_NEXT',
                    },
                },
            ]
        })
        km = KeybindManager(config)
        assert km.get_layer_count() == 2

        base_layer = km.layers[0]
        child_layer = km.layers[1]

        assert 'BUTTON_1' in base_layer
        assert 'BUTTON_2' in base_layer
        assert 'DIAL_CW' in base_layer
        assert 'DIAL_CLICK' in base_layer

        assert 'BUTTON_1' in child_layer
        assert child_layer['BUTTON_1'].keys == ['KEY_A']
        assert 'BUTTON_2' in child_layer
        assert child_layer['BUTTON_2'].keys == ['KEY_C']
        assert 'DIAL_CW' in child_layer
        assert child_layer['DIAL_CW'].keys == ['SCROLL_UP']
        assert 'DIAL_CLICK' in child_layer
        assert child_layer['DIAL_CLICK'].keys == ['LAYER_NEXT']

    @pytest.mark.keybind_manager
    def test_layer_inheritance_preserves_override(self):
        """Test that explicit bindings in child layer override inheritance."""
        config = Config({
            'layers': [
                {
                    'name': 'Base',
                    'key_mappings': {
                        'BUTTON_1': 'KEY_A',
                    },
                },
                {
                    'name': 'Child',
                    'key_mappings': {
                        'BUTTON_1': 'KEY_B',
                    },
                },
            ]
        })
        km = KeybindManager(config)
        assert km.layers[1]['BUTTON_1'].keys == ['KEY_B']
