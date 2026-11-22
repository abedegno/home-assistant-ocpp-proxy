"""OCPP proxy: native Core runtime, with optional external deployment support."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .config import build_config, deployment
from .const import DOMAIN
from .coordinator import NativeCoordinator, OCPPChargeProxyCoordinator
from .runtime import NativeRuntime

PLATFORMS = ["sensor", "binary_sensor", "switch", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = None
    if deployment(entry.data) == "native":
        try:
            config = build_config(entry.data, entry.options)
        except (TypeError, ValueError) as error:
            raise ConfigEntryError("Invalid proxy configuration") from error
        runtime = NativeRuntime(hass, entry, config)
        try:
            await runtime.async_start()
        except OSError as error:
            raise ConfigEntryNotReady(
                "Cannot start proxy listener or storage"
            ) from error
        coordinator = NativeCoordinator(
            hass, entry, runtime, entry.options.get("power_entity", "")
        )
    else:
        coordinator = OCPPChargeProxyCoordinator(
            hass, entry, entry.data["api_url"], entry.options.get("power_entity", "")
        )
    try:
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await coordinator.async_shutdown()
        if runtime is not None:
            await runtime.async_stop()
        raise
    if runtime is not None:

        async def stop(event):
            await coordinator.async_shutdown()
            await runtime.async_stop()

        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_shutdown()
    if isinstance(coordinator, NativeCoordinator):
        await coordinator.runtime.async_stop()
    hass.data[DOMAIN].pop(entry.entry_id)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version > 2:
        return False
    if entry.version == 1:
        # Existing companion entries remain external; never start another charger identity.
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "deployment": "external"},
            version=2,
            minor_version=1,
        )
    return True
