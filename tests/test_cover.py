"""Tests for the MyHOME cover time-based position tracking."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.message import OWNAutomationEvent

from custom_components.myhome.cover import MyHOMECover


def make_cover(advanced=False, opening_time=0, closing_time=0):
    """Create a MyHOMECover with mocked dependencies."""
    hass = MagicMock()
    hass.bus = MagicMock()

    gateway = MagicMock()
    gateway.mac = "aa:bb:cc:dd:ee:ff"
    gateway.unique_id = "aa:bb:cc:dd:ee:ff"
    gateway.send = AsyncMock()
    gateway.send_status_request = AsyncMock()

    with patch("custom_components.myhome.cover.async_call_later") as mock_timer:
        mock_timer.return_value = MagicMock()
        cover = MyHOMECover(
            hass=hass,
            name="Test Cover",
            entity_name=None,
            device_id="2-11",
            who="2",
            where="11",
            interface=None,
            advanced=advanced,
            opening_time=opening_time,
            closing_time=closing_time,
            manufacturer="BTicino S.p.A.",
            model="K4672",
            gateway=gateway,
        )

    cover._hass = hass
    cover.async_schedule_update_ha_state = MagicMock()
    cover.async_write_ha_state = MagicMock()
    return cover


@pytest.fixture
def time_cover():
    """A cover with time-based position (20s open, 20s close)."""
    return make_cover(opening_time=20.0, closing_time=20.0)


@pytest.fixture
def advanced_cover():
    """An advanced cover that reports position natively."""
    return make_cover(advanced=True)


@pytest.fixture
def basic_cover():
    """A basic cover with no position support."""
    return make_cover()


class TestCoverInit:
    def test_time_based_flag(self, time_cover):
        assert time_cover._time_based is True

    def test_advanced_flag(self, advanced_cover):
        assert advanced_cover._advanced is True

    def test_basic_no_time_based(self, basic_cover):
        assert basic_cover._time_based is False
        assert basic_cover._advanced is False


class TestTimeBasedMovement:
    def test_start_movement_sets_tracking_state(self, time_cover):
        time_cover._attr_current_cover_position = 50
        time_cover._start_movement(target_position=100)

        assert time_cover._movement_start_time is not None
        assert time_cover._position_at_start == 50
        assert time_cover._target_position == 100

    def test_update_position_opening(self, time_cover):
        time_cover._attr_current_cover_position = 0
        time_cover._position_at_start = 0
        time_cover._attr_is_opening = True
        time_cover._attr_is_closing = False
        time_cover._movement_start_time = time.monotonic() - 10.0  # 10s elapsed

        time_cover._update_position_from_elapsed()

        # 10s of 20s opening time = 50%
        assert time_cover._attr_current_cover_position == 50

    def test_update_position_closing(self, time_cover):
        time_cover._attr_current_cover_position = 100
        time_cover._position_at_start = 100
        time_cover._attr_is_opening = False
        time_cover._attr_is_closing = True
        time_cover._movement_start_time = time.monotonic() - 5.0  # 5s elapsed

        time_cover._update_position_from_elapsed()

        # 5s of 20s closing time = 25% travel -> 100 - 25 = 75
        assert time_cover._attr_current_cover_position == 75

    def test_position_clamped_at_100(self, time_cover):
        time_cover._attr_current_cover_position = 80
        time_cover._position_at_start = 80
        time_cover._attr_is_opening = True
        time_cover._attr_is_closing = False
        time_cover._movement_start_time = time.monotonic() - 30.0  # way past full open

        time_cover._update_position_from_elapsed()

        assert time_cover._attr_current_cover_position == 100

    def test_position_clamped_at_0(self, time_cover):
        time_cover._attr_current_cover_position = 20
        time_cover._position_at_start = 20
        time_cover._attr_is_opening = False
        time_cover._attr_is_closing = True
        time_cover._movement_start_time = time.monotonic() - 30.0  # way past full close

        time_cover._update_position_from_elapsed()

        assert time_cover._attr_current_cover_position == 0

    def test_finish_movement_clears_state(self, time_cover):
        time_cover._attr_current_cover_position = 50
        time_cover._movement_start_time = time.monotonic()
        time_cover._position_at_start = 0
        time_cover._target_position = 50
        time_cover._attr_is_opening = True

        time_cover._finish_movement()

        assert time_cover._movement_start_time is None
        assert time_cover._position_at_start is None
        assert time_cover._target_position is None
        assert time_cover._attr_is_opening is False
        assert time_cover._attr_is_closing is False


class TestTimeBasedEvents:
    def test_opening_event_starts_tracking(self, time_cover):
        time_cover._attr_current_cover_position = 0

        message = MagicMock(spec=OWNAutomationEvent)
        message.is_opening = True
        message.is_closing = False
        message.is_closed = None
        message.current_position = None
        message.human_readable_log = "Cover opening"

        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            time_cover.handle_event(message)

        assert time_cover._attr_is_opening is True
        assert time_cover._movement_start_time is not None

    def test_closing_event_starts_tracking(self, time_cover):
        time_cover._attr_current_cover_position = 100

        message = MagicMock(spec=OWNAutomationEvent)
        message.is_opening = False
        message.is_closing = True
        message.is_closed = None
        message.current_position = None
        message.human_readable_log = "Cover closing"

        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            time_cover.handle_event(message)

        assert time_cover._attr_is_closing is True
        assert time_cover._movement_start_time is not None

    def test_stop_event_calculates_position(self, time_cover):
        time_cover._attr_current_cover_position = 0
        time_cover._position_at_start = 0
        time_cover._target_position = 100
        time_cover._attr_is_opening = True
        time_cover._attr_is_closing = False
        time_cover._movement_start_time = time.monotonic() - 10.0  # 10s

        message = MagicMock(spec=OWNAutomationEvent)
        message.is_opening = False
        message.is_closing = False
        message.is_closed = None
        message.current_position = None
        message.human_readable_log = "Cover stopped"

        time_cover.handle_event(message)

        assert time_cover._attr_current_cover_position == 50
        assert time_cover._attr_is_opening is False
        assert time_cover._movement_start_time is None

    def test_stop_at_zero_sets_is_closed(self, time_cover):
        time_cover._attr_current_cover_position = 10
        time_cover._position_at_start = 10
        time_cover._target_position = 0
        time_cover._attr_is_opening = False
        time_cover._attr_is_closing = True
        time_cover._movement_start_time = time.monotonic() - 20.0  # full close

        message = MagicMock(spec=OWNAutomationEvent)
        message.is_opening = False
        message.is_closing = False
        message.is_closed = None
        message.current_position = None
        message.human_readable_log = "Cover stopped"

        time_cover.handle_event(message)

        assert time_cover._attr_current_cover_position == 0
        assert time_cover._attr_is_closed is True


class TestAdvancedCoverEvents:
    def test_position_from_message(self, advanced_cover):
        message = MagicMock(spec=OWNAutomationEvent)
        message.is_opening = False
        message.is_closing = False
        message.is_closed = False
        message.current_position = 75
        message.human_readable_log = "Cover at 75%"

        advanced_cover.handle_event(message)

        assert advanced_cover._attr_current_cover_position == 75

    def test_no_time_tracking(self, advanced_cover):
        """Advanced covers don't use time-based tracking."""
        message = MagicMock(spec=OWNAutomationEvent)
        message.is_opening = True
        message.is_closing = False
        message.is_closed = None
        message.current_position = None
        message.human_readable_log = "Cover opening"

        advanced_cover.handle_event(message)

        assert advanced_cover._movement_start_time is None


class TestSetCoverPosition:
    @pytest.mark.asyncio
    async def test_advanced_sends_level_command(self, advanced_cover):
        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            await advanced_cover.async_set_cover_position(**{"position": 50})
        advanced_cover._gateway_handler.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_time_based_no_current_position_does_nothing(self, time_cover):
        """If we don't know current position, can't calculate travel."""
        time_cover._attr_current_cover_position = None
        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            await time_cover.async_set_cover_position(**{"position": 50})
        time_cover._gateway_handler.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_time_based_same_position_does_nothing(self, time_cover):
        time_cover._attr_current_cover_position = 50
        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            await time_cover.async_set_cover_position(**{"position": 50})
        time_cover._gateway_handler.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_time_based_opens_for_higher_target(self, time_cover):
        time_cover._attr_current_cover_position = 30

        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            await time_cover.async_set_cover_position(**{"position": 80})

        assert time_cover._gateway_handler.send.called
        assert time_cover._target_position == 80

    @pytest.mark.asyncio
    async def test_time_based_closes_for_lower_target(self, time_cover):
        time_cover._attr_current_cover_position = 80

        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            await time_cover.async_set_cover_position(**{"position": 30})

        assert time_cover._gateway_handler.send.called
        assert time_cover._target_position == 30

    @pytest.mark.asyncio
    async def test_basic_cover_ignores_set_position(self, basic_cover):
        basic_cover._attr_current_cover_position = 50
        with patch("custom_components.myhome.cover.async_call_later", return_value=MagicMock()):
            await basic_cover.async_set_cover_position(**{"position": 80})
        basic_cover._gateway_handler.send.assert_not_called()
