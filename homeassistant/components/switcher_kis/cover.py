"""Switcher integration Cover platform."""

from __future__ import annotations

import logging
from typing import Any, cast

from aioswitcher.api import SwitcherApi, SwitcherBaseResponse
from aioswitcher.device import DeviceCategory, ShutterDirection, SwitcherShutter

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_DEVICE_ADD
from .coordinator import SwitcherDataUpdateCoordinator
from .entity import SwitcherEntity

_LOGGER = logging.getLogger(__name__)

API_SET_POSITON = "set_position"
API_STOP = "stop_shutter"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Switcher cover from config entry."""

    @callback
    def async_add_cover(coordinator: SwitcherDataUpdateCoordinator) -> None:
        """Add cover from Switcher device."""
        entities: list[CoverEntity] = []

        if coordinator.data.device_type.category in (
            DeviceCategory.SHUTTER,
            DeviceCategory.SINGLE_SHUTTER_DUAL_LIGHT,
            DeviceCategory.DUAL_SHUTTER_SINGLE_LIGHT,
        ):
            number_of_covers = len(cast(SwitcherShutter, coordinator.data).position)
            if number_of_covers == 1:
                entities.append(SwitcherSingleCoverEntity(coordinator, 0))
            else:
                entities.extend(
                    SwitcherMultiCoverEntity(coordinator, i)
                    for i in range(number_of_covers)
                )
        async_add_entities(entities)

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_ADD, async_add_cover)
    )


class SwitcherBaseCoverEntity(SwitcherEntity, CoverEntity):
    """Representation of a Switcher cover entity."""

    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )
    _cover_id: int

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_data()
        self.async_write_ha_state()

    def _update_data(self) -> None:
        """Update data from device."""
        data = cast(SwitcherShutter, self.coordinator.data)
        self._attr_current_cover_position = data.position[self._cover_id]
        self._attr_is_closed = data.position[self._cover_id] == 0
        self._attr_is_closing = (
            data.direction[self._cover_id] == ShutterDirection.SHUTTER_DOWN
        )
        self._attr_is_opening = (
            data.direction[self._cover_id] == ShutterDirection.SHUTTER_UP
        )

    async def _async_call_api(self, api: str, *args: Any) -> None:
        """Call Switcher API."""
        _LOGGER.debug("Calling api for %s, api: '%s', args: %s", self.name, api, args)
        response: SwitcherBaseResponse | None = None
        error = None

        try:
            async with SwitcherApi(
                self.coordinator.data.device_type,
                self.coordinator.data.ip_address,
                self.coordinator.data.device_id,
                self.coordinator.data.device_key,
                self.coordinator.token,
            ) as swapi:
                response = await getattr(swapi, api)(*args)
        except (TimeoutError, OSError, RuntimeError) as err:
            error = repr(err)

        if error or not response or not response.successful:
            self.coordinator.last_update_success = False
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Call api for {self.name} failed, api: '{api}', "
                f"args: {args}, response/error: {response or error}"
            )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        await self._async_call_api(API_SET_POSITON, 0, self._cover_id)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open cover."""
        await self._async_call_api(API_SET_POSITON, 100, self._cover_id)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        await self._async_call_api(
            API_SET_POSITON, kwargs[ATTR_POSITION], self._cover_id
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._async_call_api(API_STOP, self._cover_id)


class SwitcherSingleCoverEntity(SwitcherBaseCoverEntity):
    """Representation of a Switcher single cover entity."""

    _attr_name = None

    def __init__(
        self,
        coordinator: SwitcherDataUpdateCoordinator,
        cover_id: int,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._cover_id = cover_id

        self._attr_unique_id = f"{coordinator.device_id}-{coordinator.mac_address}"

        self._update_data()


class SwitcherMultiCoverEntity(SwitcherBaseCoverEntity):
    """Representation of a Switcher multiple cover entity."""

    _attr_translation_key = "cover"

    def __init__(
        self,
        coordinator: SwitcherDataUpdateCoordinator,
        cover_id: int,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._cover_id = cover_id

        self._attr_translation_placeholders = {"cover_id": str(cover_id + 1)}
        self._attr_unique_id = (
            f"{coordinator.device_id}-{coordinator.mac_address}-{cover_id}"
        )

        self._update_data()
