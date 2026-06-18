"""Support for MyHome covers."""
import time

from homeassistant.components.cover import (
    ATTR_POSITION,
    DOMAIN as PLATFORM,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from OWNd.message import (
    OWNAutomationEvent,
    OWNAutomationCommand,
)

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_ENTITY_NAME,
    CONF_WHO,
    CONF_WHERE,
    CONF_BUS_INTERFACE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_ADVANCED_SHUTTER,
    CONF_OPENING_TIME,
    CONF_CLOSING_TIME,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _covers = []
    _configured_covers = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _cover in _configured_covers.keys():
        _cover = MyHOMECover(
            hass=hass,
            device_id=_cover,
            who=_configured_covers[_cover][CONF_WHO],
            where=_configured_covers[_cover][CONF_WHERE],
            interface=_configured_covers[_cover][CONF_BUS_INTERFACE] if CONF_BUS_INTERFACE in _configured_covers[_cover] else None,
            name=_configured_covers[_cover][CONF_NAME],
            entity_name=_configured_covers[_cover][CONF_ENTITY_NAME],
            advanced=_configured_covers[_cover][CONF_ADVANCED_SHUTTER],
            opening_time=_configured_covers[_cover][CONF_OPENING_TIME],
            closing_time=_configured_covers[_cover][CONF_CLOSING_TIME],
            manufacturer=_configured_covers[_cover][CONF_MANUFACTURER],
            model=_configured_covers[_cover][CONF_DEVICE_MODEL],
            gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
        )
        _covers.append(_cover)

    async_add_entities(_covers)


async def async_unload_entry(hass, config_entry):  # pylint: disable=unused-argument
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_covers = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _cover in _configured_covers.keys():
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_cover]


class MyHOMECover(MyHOMEEntity, RestoreEntity, CoverEntity):
    device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        interface: str,
        advanced: bool,
        opening_time: float,
        closing_time: float,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._attr_name = entity_name

        self._interface = interface
        self._full_where = f"{self._where}#4#{self._interface}" if self._interface is not None else self._where

        self._advanced = advanced
        self._opening_time = opening_time
        self._closing_time = closing_time
        self._time_based = opening_time > 0 and closing_time > 0 and not advanced

        self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if advanced or self._time_based:
            self._attr_supported_features |= CoverEntityFeature.SET_POSITION
        self._gateway_handler = gateway

        self._attr_extra_state_attributes = {
            "A": where[: len(where) // 2],
            "PL": where[len(where) // 2 :],
        }
        if self._interface is not None:
            self._attr_extra_state_attributes["Int"] = self._interface

        self._attr_current_cover_position = None
        self._attr_is_opening = None
        self._attr_is_closing = None
        self._attr_is_closed = None

        self._movement_start_time = None
        self._position_at_start = None
        self._target_position = None
        self._stop_timer_cancel = None
        self._update_timer_cancel = None

    async def async_added_to_hass(self):
        """Restore last known position on startup."""
        await super().async_added_to_hass()

        if self._time_based:
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.attributes.get("current_position") is not None:
                self._attr_current_cover_position = int(last_state.attributes["current_position"])
                self._attr_is_closed = self._attr_current_cover_position == 0

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(OWNAutomationCommand.status(self._full_where))

    async def async_open_cover(self, **kwargs):  # pylint: disable=unused-argument
        """Open the cover."""
        if self._time_based:
            self._start_movement(target_position=100)
        await self._gateway_handler.send(OWNAutomationCommand.raise_shutter(self._full_where))

    async def async_close_cover(self, **kwargs):  # pylint: disable=unused-argument
        """Close cover."""
        if self._time_based:
            self._start_movement(target_position=0)
        await self._gateway_handler.send(OWNAutomationCommand.lower_shutter(self._full_where))

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        if ATTR_POSITION not in kwargs:
            return

        position = kwargs[ATTR_POSITION]

        if self._advanced:
            await self._gateway_handler.send(OWNAutomationCommand.set_shutter_level(self._full_where, position))
            return

        if not self._time_based:
            return

        if self._attr_current_cover_position is None:
            return

        if position == self._attr_current_cover_position:
            return

        self._start_movement(target_position=position)

        if position > self._attr_current_cover_position:
            await self._gateway_handler.send(OWNAutomationCommand.raise_shutter(self._full_where))
        else:
            await self._gateway_handler.send(OWNAutomationCommand.lower_shutter(self._full_where))

        travel_percentage = abs(position - self._position_at_start)
        if position > self._position_at_start:
            travel_time = self._opening_time * travel_percentage / 100
        else:
            travel_time = self._closing_time * travel_percentage / 100

        self._stop_timer_cancel = async_call_later(
            self._hass, travel_time, self._async_stop_at_target
        )

    async def async_stop_cover(self, **kwargs):  # pylint: disable=unused-argument
        """Stop the cover."""
        self._cancel_timers()
        if self._time_based and self._movement_start_time is not None:
            self._update_position_from_elapsed()
            self._finish_movement()
        await self._gateway_handler.send(OWNAutomationCommand.stop_shutter(self._full_where))

    @callback
    def _async_stop_at_target(self, _now):
        """Called when the cover should have reached target position."""
        self._cancel_timers()
        if self._target_position is not None:
            self._attr_current_cover_position = self._target_position
        self._finish_movement()
        self.async_write_ha_state()
        self._hass.async_create_task(
            self._gateway_handler.send(OWNAutomationCommand.stop_shutter(self._full_where))
        )

    def _start_movement(self, target_position: int):
        """Begin tracking a time-based movement."""
        self._cancel_timers()
        if self._attr_current_cover_position is not None:
            self._position_at_start = self._attr_current_cover_position
        else:
            self._position_at_start = 0 if target_position > 50 else 100
            self._attr_current_cover_position = self._position_at_start
        self._target_position = target_position
        self._movement_start_time = time.monotonic()

        self._schedule_position_updates()

    def _finish_movement(self):
        """End movement tracking."""
        self._movement_start_time = None
        self._position_at_start = None
        self._target_position = None
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed = self._attr_current_cover_position == 0

    def _update_position_from_elapsed(self):
        """Calculate current position based on elapsed time."""
        if self._movement_start_time is None or self._position_at_start is None:
            return

        elapsed = time.monotonic() - self._movement_start_time

        if self._attr_is_opening:
            travel = (elapsed / self._opening_time) * 100
            new_position = min(100, self._position_at_start + travel)
        elif self._attr_is_closing:
            travel = (elapsed / self._closing_time) * 100
            new_position = max(0, self._position_at_start - travel)
        else:
            return

        self._attr_current_cover_position = int(round(new_position))

    def _schedule_position_updates(self):
        """Schedule periodic UI updates during movement."""
        @callback
        def _update_tick(_now):
            if self._movement_start_time is None:
                return
            self._update_position_from_elapsed()
            self._attr_is_closed = self._attr_current_cover_position == 0
            self.async_write_ha_state()
            self._update_timer_cancel = async_call_later(
                self._hass, 1.0, _update_tick
            )

        self._update_timer_cancel = async_call_later(
            self._hass, 1.0, _update_tick
        )

    def _cancel_timers(self):
        """Cancel any pending timers."""
        if self._stop_timer_cancel is not None:
            self._stop_timer_cancel()
            self._stop_timer_cancel = None
        if self._update_timer_cancel is not None:
            self._update_timer_cancel()
            self._update_timer_cancel = None

    def handle_event(self, message: OWNAutomationEvent):
        """Handle an event message."""
        LOGGER.info(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )

        if self._time_based:
            self._handle_time_based_event(message)
        else:
            if message.current_position is not None:
                self._attr_current_cover_position = message.current_position
            self._attr_is_opening = message.is_opening
            self._attr_is_closing = message.is_closing
            if message.is_closed is not None:
                self._attr_is_closed = message.is_closed

        self.async_schedule_update_ha_state()

    def _handle_time_based_event(self, message: OWNAutomationEvent):
        """Handle events for time-based covers, tracking position from movement duration."""
        was_moving = self._movement_start_time is not None

        if message.is_opening:
            if not was_moving:
                self._start_movement(target_position=100)
            self._attr_is_opening = True
            self._attr_is_closing = False
        elif message.is_closing:
            if not was_moving:
                self._start_movement(target_position=0)
            self._attr_is_opening = False
            self._attr_is_closing = True
        else:
            # Stopped (either by user, physical button, or our scheduled stop)
            self._cancel_timers()
            if was_moving:
                self._update_position_from_elapsed()
                self._finish_movement()
            self._attr_is_opening = False
            self._attr_is_closing = False

        if self._attr_current_cover_position is not None:
            self._attr_is_closed = self._attr_current_cover_position == 0
