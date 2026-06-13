"""Tests for the Bluetooth device connection watcher."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dbus_next import MessageFlag
from dbus_next.constants import MessageType
from dbus_next.message import Message

from huion_keydial_mini.bluetooth_watcher import BluetoothWatcher

_NO_FLAGS = MessageFlag(0)


def _make_signal_message(path, body):
    return Message(
        message_type=MessageType.SIGNAL,
        flags=_NO_FLAGS,
        serial=1,
        destination=None,
        path=path,
        interface="org.freedesktop.DBus.Properties",
        member="PropertiesChanged",
        signature="sa{sv}as",
        body=body,
    )


def _make_variant(value):
    class Variant:
        def __init__(self, v):
            self.value = v
    return Variant(value)


class TestBluetoothWatcherPathToMac:
    def test_hci0(self):
        watcher = BluetoothWatcher()
        assert watcher._dbus_path_to_mac("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF") == "AA:BB:CC:DD:EE:FF"

    def test_hci1(self):
        watcher = BluetoothWatcher()
        assert watcher._dbus_path_to_mac("/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF") == "AA:BB:CC:DD:EE:FF"

    def test_hci2(self):
        watcher = BluetoothWatcher()
        assert watcher._dbus_path_to_mac("/org/bluez/hci2/dev_11_22_33_44_55_66") == "11:22:33:44:55:66"

    def test_non_device_path_adapter(self):
        watcher = BluetoothWatcher()
        assert watcher._dbus_path_to_mac("/org/bluez/hci0") == ""

    def test_non_device_path_root(self):
        watcher = BluetoothWatcher()
        assert watcher._dbus_path_to_mac("/org/bluez") == ""

    def test_non_device_path_empty(self):
        watcher = BluetoothWatcher()
        assert watcher._dbus_path_to_mac("") == ""

    def test_runtime_input(self):
        watcher = BluetoothWatcher()
        path = "/org/bluez/hci1/dev_20_23_06_01_B6_DD"
        assert watcher._dbus_path_to_mac(path) == "20:23:06:01:B6:DD"


class MockMessage:

    def __init__(self, message_type, path, interface, member, body, sender="org.bluez"):
        self.message_type = message_type
        self.path = path
        self.interface = interface
        self.member = member
        self.body = body
        self.sender = sender


class TestBluetoothWatcherHandleMessage:

    @pytest.fixture
    def callback(self):
        return AsyncMock()

    @pytest.fixture
    def watcher(self, callback):
        w = BluetoothWatcher(on_connect_callback=callback)
        w.running = True
        return w

    def _connected_props(self):
        return ["org.bluez.Device1", {"Connected": _make_variant(True)}, []]

    def _make_signal(self, path, body):
        return _make_signal_message(path, body)

    @pytest.mark.asyncio
    async def test_processes_signal_on_hci0(self, watcher, callback):
        msg = self._make_signal(
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_processes_signal_on_hci1(self, watcher, callback):
        msg = self._make_signal(
            "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_processes_signal_on_hci2(self, watcher, callback):
        msg = self._make_signal(
            "/org/bluez/hci2/dev_11_22_33_44_55_66",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_signal_with_empty_path(self, watcher, callback):
        msg = MagicMock()
        msg.message_type = MessageType.SIGNAL
        msg.interface = "org.freedesktop.DBus.Properties"
        msg.member = "PropertiesChanged"
        msg.path = ""
        msg.body = ["org.bluez.Device1", {"Connected": _make_variant(True)}, []]
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_signal_with_non_device_path(self, watcher, callback):
        msg = self._make_signal(
            "/org/bluez/hci0",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_signal_messages(self, watcher, callback):
        msg = MagicMock()
        msg.message_type = MessageType.METHOD_RETURN
        msg.interface = "org.freedesktop.DBus.Properties"
        msg.member = "PropertiesChanged"
        msg.path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_properties_interface(self, watcher, callback):
        msg = MagicMock()
        msg.message_type = MessageType.SIGNAL
        msg.interface = "org.example.Wrong"
        msg.member = "SomeSignal"
        msg.path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_by_target_mac_match(self, watcher, callback):
        watcher.target_mac = "AA:BB:CC:DD:EE:FF"
        msg = self._make_signal(
            "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_filters_by_target_mac_mismatch(self, watcher, callback):
        watcher.target_mac = "AA:BB:CC:DD:EE:FF"
        msg = self._make_signal(
            "/org/bluez/hci1/dev_11_22_33_44_55_66",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_return_when_not_running(self, watcher, callback):
        watcher.running = False
        msg = self._make_signal(
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF",
            self._connected_props(),
        )
        with patch.object(watcher, '_handle_device_property_change', AsyncMock()) as mock_handle:
            watcher._handle_message(msg)
            await asyncio.sleep(0)
            mock_handle.assert_not_called()
