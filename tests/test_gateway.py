"""Tests for the MyHOME gateway listening loop resilience."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from OWNd.message import OWNLightingEvent, OWNMessage
from OWNd.connection import OWNEventSession

from custom_components.myhome.gateway import MyHOMEGatewayHandler


def make_gateway_handler(generate_events=False):
    """Create a MyHOMEGatewayHandler with mocked dependencies."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.data = {}

    config_entry = MagicMock()
    config_entry.data = {
        "host": "192.168.1.100",
        "port": 20000,
        "password": "12345",
        "ssdp_location": "http://192.168.1.100:8080/desc.xml",
        "ssdp_st": "upnp:rootdevice",
        "deviceType": "gateway",
        "friendly_name": "Test Gateway",
        "manufacturer": "BTicino S.p.A.",
        "manufacturerURL": "http://www.bticino.it",
        "name": "F455",
        "firmware": "1.0.0",
        "mac": "AA:BB:CC:DD:EE:FF",
        "UDN": "uuid:test",
    }

    with patch("OWNd.connection.OWNGateway") as mock_gw_class:
        mock_gw = MagicMock()
        mock_gw.host = "192.168.1.100"
        mock_gw.serial = "aa:bb:cc:dd:ee:ff"
        mock_gw.log_id = "[Test]"
        mock_gw.model_name = "F455"
        mock_gw.manufacturer = "BTicino S.p.A."
        mock_gw.firmware = "1.0.0"
        mock_gw_class.return_value = mock_gw

        handler = MyHOMEGatewayHandler(
            hass=hass,
            config_entry=config_entry,
            generate_events=generate_events,
        )

    return handler


@pytest.fixture
def gateway_handler():
    return make_gateway_handler()


class TestListeningLoopResilience:
    """Tests that the listening loop survives errors without dying."""

    @pytest.mark.asyncio
    async def test_continues_after_get_next_raises(self, gateway_handler):
        """If get_next() throws, the loop should log and continue."""
        call_count = 0

        async def mock_get_next():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Connection blip")
            elif call_count == 2:
                gateway_handler._terminate_listener = True
                return MagicMock(spec=OWNMessage)
            return None

        with patch.object(OWNEventSession, "__init__", return_value=None), \
             patch.object(OWNEventSession, "connect", new_callable=AsyncMock), \
             patch.object(OWNEventSession, "get_next", side_effect=mock_get_next), \
             patch.object(OWNEventSession, "close", new_callable=AsyncMock):

            gateway_handler.listening_worker = MagicMock()
            await gateway_handler.listening_loop()

        assert call_count == 2, "Loop should have continued past the first exception"

    @pytest.mark.asyncio
    async def test_continues_after_message_dispatch_raises(self, gateway_handler):
        """If dispatching a message throws (e.g. KeyError for unconfigured device), loop continues."""
        mac = gateway_handler.mac
        gateway_handler.hass.data = {
            "myhome": {
                mac: {
                    "platforms": {}
                }
            }
        }

        call_count = 0
        mock_event = MagicMock(spec=OWNLightingEvent)
        mock_event.is_translation = False
        mock_event.is_general = False
        mock_event.is_area = False
        mock_event.is_group = False
        mock_event.brightness_preset = False
        mock_event.entity = "1-99"  # Non-existent entity -> will cause KeyError in dispatch

        async def mock_get_next():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_event
            else:
                gateway_handler._terminate_listener = True
                return MagicMock(spec=OWNMessage)

        with patch.object(OWNEventSession, "__init__", return_value=None), \
             patch.object(OWNEventSession, "connect", new_callable=AsyncMock), \
             patch.object(OWNEventSession, "get_next", side_effect=mock_get_next), \
             patch.object(OWNEventSession, "close", new_callable=AsyncMock):

            gateway_handler.listening_worker = MagicMock()
            await gateway_handler.listening_loop()

        assert call_count == 2, "Loop should have survived the dispatch error"

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self, gateway_handler):
        """asyncio.CancelledError must not be swallowed — HA needs it to stop tasks."""
        async def mock_get_next():
            raise asyncio.CancelledError()

        with patch.object(OWNEventSession, "__init__", return_value=None), \
             patch.object(OWNEventSession, "connect", new_callable=AsyncMock), \
             patch.object(OWNEventSession, "get_next", side_effect=mock_get_next), \
             patch.object(OWNEventSession, "close", new_callable=AsyncMock):

            gateway_handler.listening_worker = MagicMock()
            with pytest.raises(asyncio.CancelledError):
                await gateway_handler.listening_loop()

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_from_dispatch(self, gateway_handler):
        """CancelledError during dispatch must also propagate."""
        mac = gateway_handler.mac
        gateway_handler.hass.data = {
            "myhome": {
                mac: {
                    "platforms": {
                        "light": {}
                    }
                }
            }
        }

        mock_event = MagicMock(spec=OWNLightingEvent)
        mock_event.is_translation = False
        mock_event.is_general = False
        mock_event.is_area = False
        mock_event.is_group = False
        mock_event.brightness_preset = True
        mock_event.entity = "1-11"

        # Make the entity lookup raise CancelledError
        platforms_dict = MagicMock()
        platforms_dict.__contains__ = lambda self, x: x != "button"
        platforms_dict.__iter__ = lambda self: iter(["light"])
        platforms_dict.__getitem__ = MagicMock(side_effect=asyncio.CancelledError())
        gateway_handler.hass.data["myhome"][mac]["platforms"] = platforms_dict

        call_count = 0

        async def mock_get_next():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_event
            gateway_handler._terminate_listener = True
            return MagicMock(spec=OWNMessage)

        with patch.object(OWNEventSession, "__init__", return_value=None), \
             patch.object(OWNEventSession, "connect", new_callable=AsyncMock), \
             patch.object(OWNEventSession, "get_next", side_effect=mock_get_next), \
             patch.object(OWNEventSession, "close", new_callable=AsyncMock):

            gateway_handler.listening_worker = MagicMock()
            with pytest.raises(asyncio.CancelledError):
                await gateway_handler.listening_loop()

    @pytest.mark.asyncio
    async def test_is_connected_flag(self, gateway_handler):
        """is_connected should be True while listening and False after exit."""
        async def mock_get_next():
            assert gateway_handler.is_connected is True
            gateway_handler._terminate_listener = True
            return MagicMock(spec=OWNMessage)

        with patch.object(OWNEventSession, "__init__", return_value=None), \
             patch.object(OWNEventSession, "connect", new_callable=AsyncMock), \
             patch.object(OWNEventSession, "get_next", side_effect=mock_get_next), \
             patch.object(OWNEventSession, "close", new_callable=AsyncMock):

            gateway_handler.listening_worker = MagicMock()
            await gateway_handler.listening_loop()

        assert gateway_handler.is_connected is False


class TestSendingLoop:
    """Tests for the command sending worker."""

    @pytest.mark.asyncio
    async def test_send_queues_message(self, gateway_handler):
        """send() should put message on the buffer."""
        mock_message = MagicMock()
        await gateway_handler.send(mock_message)

        queued = gateway_handler.send_buffer.get_nowait()
        assert queued["message"] is mock_message
        assert queued["is_status_request"] is False

    @pytest.mark.asyncio
    async def test_send_status_request_queues_message(self, gateway_handler):
        """send_status_request() should put message on the buffer with is_status_request=True."""
        mock_message = MagicMock()
        await gateway_handler.send_status_request(mock_message)

        queued = gateway_handler.send_buffer.get_nowait()
        assert queued["message"] is mock_message
        assert queued["is_status_request"] is True


class TestStop:
    """Tests for the stop() method that cleanly shuts down workers."""

    @pytest.fixture
    def gateway_handler(self):
        return make_gateway_handler()

    @pytest.mark.asyncio
    async def test_stop_cancels_listening_worker(self, gateway_handler):
        """stop() should cancel the listening worker and await it."""
        async def block_forever():
            await asyncio.sleep(999)

        task = asyncio.ensure_future(block_forever())
        gateway_handler.listening_worker = task

        await gateway_handler.stop()

        assert task.cancelled()
        assert gateway_handler._terminate_listener is True
        assert gateway_handler._terminate_sender is True

    @pytest.mark.asyncio
    async def test_stop_cancels_all_sending_workers(self, gateway_handler):
        """stop() should cancel all sending workers."""
        async def block_forever():
            await asyncio.sleep(999)

        tasks = [asyncio.ensure_future(block_forever()) for _ in range(3)]
        gateway_handler.sending_workers = tasks

        await gateway_handler.stop()

        for task in tasks:
            assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_handles_cancelled_error_from_workers(self, gateway_handler):
        """stop() should handle CancelledError raised when awaiting cancelled tasks."""

        async def raise_cancelled():
            raise asyncio.CancelledError()

        listening_task = asyncio.ensure_future(raise_cancelled())
        # Let it raise
        await asyncio.sleep(0)

        gateway_handler.listening_worker = listening_task

        # Should not raise
        await gateway_handler.stop()

    @pytest.mark.asyncio
    async def test_stop_with_no_workers(self, gateway_handler):
        """stop() should handle the case where no workers were started."""
        assert gateway_handler.listening_worker is None
        assert gateway_handler.sending_workers == []

        # Should not raise
        await gateway_handler.stop()
