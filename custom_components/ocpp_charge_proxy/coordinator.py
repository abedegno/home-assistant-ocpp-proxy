"""Data update coordinator for OCPP Charge Proxy."""

from __future__ import annotations

import logging
import math
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfPower
from homeassistant.util.unit_conversion import PowerConverter
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import SCAN_INTERVAL

logger = logging.getLogger(__name__)


def read_power_kw(hass, entity_id):
    try:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit not in PowerConverter.VALID_UNITS:
            return None
        value = PowerConverter.convert(float(state.state), unit, UnitOfPower.KILO_WATT)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


class OCPPChargeProxyCoordinator(DataUpdateCoordinator):
    """Coordinator that polls the OCPP Charge Proxy add-on API."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api_url: str,
        power_entity: str = "",
    ) -> None:
        super().__init__(
            hass,
            logger,
            name="OCPP Charge Proxy",
            config_entry=config_entry,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self._api_url = api_url
        self._power_entity = power_entity
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict:
        try:
            async with self._session.get(
                f"{self._api_url}/api/state",
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            if self._power_entity and data.get("mode", "emulator") != "relay":
                await self._push_power_reading()
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with add-on: {err}") from err

    async def _push_power_reading(self) -> None:
        """Read power entity from HA and push to the add-on."""
        power_kw = read_power_kw(self.hass, self._power_entity)

        try:
            async with self._session.post(
                f"{self._api_url}/api/power",
                json={"power_kw": power_kw},
                timeout=3,
            ) as response:
                response.raise_for_status()
        except Exception:
            logger.debug("Failed to push power reading to add-on", exc_info=True)

    async def send_command(self, endpoint: str, json: dict | None = None) -> None:
        """Send a command to the add-on API."""
        if self.data and self.data.get("mode") == "relay":
            raise HomeAssistantError("Relay mode is read-only")
        url = f"{self._api_url}{endpoint}"
        try:
            async with self._session.post(url, json=json, timeout=5) as resp:
                resp.raise_for_status()
        except Exception as err:
            raise HomeAssistantError(f"Failed to send command: {err}") from err


class NativeCoordinator(DataUpdateCoordinator):
    """Expose a Core-owned runtime through the existing entity interface."""

    def __init__(self, hass, config_entry, runtime, power_entity=""):
        super().__init__(
            hass,
            logger,
            name="OCPP Charge Proxy",
            config_entry=config_entry,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.runtime = runtime
        self._power_entity = power_entity

    async def _async_update_data(self):
        if self._power_entity and self.runtime.config.mode == "emulator":
            await self.runtime.async_command(
                "/api/power", {"power_kw": read_power_kw(self.hass, self._power_entity)}
            )
        return self.runtime.snapshot()

    async def send_command(self, endpoint, json=None):
        await self.runtime.async_command(endpoint, json)
