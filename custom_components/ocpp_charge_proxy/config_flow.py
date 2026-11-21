"""One native installation, with an explicit optional standalone connection."""

from __future__ import annotations

import math
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .config import DEFAULTS, build_config, deployment
from .const import DOMAIN
from .storage import AsyncPersistence


async def _try_connect(hass, url):
    try:
        async with async_get_clientsession(hass).get(
            f"{url}/api/state", timeout=3
        ) as response:
            response.raise_for_status()
            state = await response.json()
            return isinstance(state, dict) and "state" in state
    except Exception:
        return False


def power_field():
    return EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power"))


def power_key(default=""):
    # An empty string is not a valid entity ID when HA validates the form.
    return (
        vol.Optional("power_entity", default=default)
        if default
        else vol.Optional("power_entity")
    )


class OCPPChargeProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self):
        self._pending = {}
        self._options = {}
        self._editing = None
        self._discovered_url = None
        self._export = {}

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._pending = {"deployment": user_input["deployment"]}
            if user_input["deployment"] == "external":
                if (
                    self._editing is not None
                    and deployment(self._editing.data) == "native"
                ):
                    return await self.async_step_stop_native()
                return await self.async_step_external()
            return await self.async_step_native()
        default = deployment(self._editing.data) if self._editing else "native"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("deployment", default=default): vol.In(
                        {
                            "native": "Run in Home Assistant",
                            "external": "Connect to standalone proxy",
                        }
                    )
                }
            ),
        )

    def _defaults(self):
        values = {
            **DEFAULTS,
            **(dict(self._editing.data) if self._editing else {}),
            **self._pending,
        }
        coordinator = (
            self.hass.data.get(DOMAIN, {}).get(self._editing.entry_id)
            if self._editing
            else None
        )
        if coordinator is not None:
            data = coordinator.data or {}
            value = data.get("energy_kwh")
            if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                values["initial_energy_wh"] = round(value * 1000)
            runtime = getattr(coordinator, "runtime", None)
            if runtime is not None and runtime.persistence is not None:
                values["charger_serial"] = (
                    values.get("charger_serial")
                    or runtime.persistence.load_serial_number()
                )
        values.update(self._export)
        return values

    async def async_step_stop_native(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not user_input.get("confirm_stop"):
                errors["base"] = "confirm_required"
            else:
                coordinator = self.hass.data.get(DOMAIN, {}).get(self._editing.entry_id)
                runtime = getattr(coordinator, "runtime", None)
                self._export = self._defaults()
                if (
                    runtime is None
                    and self._editing.data.get("mode", "emulator") == "emulator"
                ):
                    try:
                        self._export.update(
                            await AsyncPersistence.async_read_snapshot(
                                self.hass.config.path(DOMAIN, self._editing.entry_id),
                                self._editing.data.get("charger_serial", ""),
                            )
                        )
                    except (OSError, ValueError, KeyError, TypeError):
                        errors["base"] = "handoff_unavailable"
                if not errors:
                    try:
                        stopped = await self.hass.config_entries.async_unload(
                            self._editing.entry_id
                        )
                    except Exception:
                        stopped = False
                    if not stopped:
                        errors["base"] = "cannot_stop"
                    else:
                        if runtime is not None and runtime.persistence is not None:
                            self._export["initial_energy_wh"] = (
                                runtime.persistence.load_energy_register_wh()
                            )
                            self._export["charger_serial"] = (
                                self._editing.data.get("charger_serial")
                                or runtime.persistence.load_serial_number()
                            )
                        return await self.async_step_external()
        return self.async_show_form(
            step_id="stop_native",
            data_schema=vol.Schema({vol.Required("confirm_stop", default=False): bool}),
            errors=errors,
        )

    async def async_step_native(self, user_input=None):
        errors = {}
        defaults = self._defaults()
        if user_input is not None:
            candidate = {**defaults, **user_input, "deployment": "native"}
            candidate.pop("api_url", None)
            try:
                build_config(candidate)
            except (ValueError, TypeError):
                errors["base"] = "invalid_config"
            else:
                self._pending = candidate
                self._options["power_entity"] = candidate.pop("power_entity", "")
                return await (
                    self.async_step_relay()
                    if candidate["mode"] == "relay"
                    else self.async_step_emulator()
                )
        schema = {
            vol.Required("mode", default=defaults["mode"]): vol.In(
                {"emulator": "Emulator", "relay": "Transparent relay"}
            ),
            vol.Required(
                "server_hostname", default=defaults.get("server_hostname", "")
            ): str,
            vol.Required(
                "chargepoint_id", default=defaults.get("chargepoint_id", "")
            ): str,
            vol.Required(
                "password", default=defaults.get("password", "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            power_key(
                self._editing.options.get("power_entity", "") if self._editing else ""
            ): power_field(),
        }
        return self.async_show_form(
            step_id="native", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_relay(self, user_input=None):
        errors = {}
        defaults = self._defaults()
        if user_input is not None:
            candidate = {**self._pending, **user_input}
            try:
                build_config(candidate)
            except (ValueError, TypeError):
                errors["base"] = "invalid_config"
            else:
                return await self._finish(candidate)
        return self.async_show_form(
            step_id="relay",
            data_schema=vol.Schema(
                {
                    vol.Required("relay_host", default=defaults["relay_host"]): str,
                    vol.Required("relay_port", default=defaults["relay_port"]): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Optional(
                        "relay_certfile", default=defaults["relay_certfile"]
                    ): str,
                    vol.Optional(
                        "relay_keyfile", default=defaults["relay_keyfile"]
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_emulator(self, user_input=None):
        errors = {}
        defaults = self._defaults()
        handoff = (
            self._editing is not None and deployment(self._editing.data) == "external"
        )
        if user_input is not None:
            candidate = {**self._pending, **user_input}
            if handoff and not candidate.get("charger_serial"):
                errors["charger_serial"] = "handoff_serial_required"
            else:
                try:
                    build_config(candidate)
                except (ValueError, TypeError):
                    errors["base"] = "invalid_config"
                else:
                    if handoff:
                        candidate["handoff_token"] = uuid4().hex
                    return await self._finish(candidate)
        schema = {
            vol.Required("charger_model", default=defaults["charger_model"]): str,
            vol.Required("charger_vendor", default=defaults["charger_vendor"]): str,
            vol.Optional("charger_serial", default=defaults["charger_serial"]): str,
            vol.Required("firmware_version", default=defaults["firmware_version"]): str,
            vol.Required("current_amps", default=defaults["current_amps"]): vol.In(
                [6, 10, 13, 16, 20, 25, 32]
            ),
        }
        if self._editing is None or handoff:
            schema[
                vol.Required("initial_energy_wh", default=defaults["initial_energy_wh"])
            ] = vol.All(vol.Coerce(int), vol.Range(min=0))
        return self.async_show_form(
            step_id="emulator", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_external(self, user_input=None):
        errors = {}
        defaults = self._defaults()
        if user_input is not None:
            url = user_input["api_url"].rstrip("/")
            if await _try_connect(self.hass, url):
                self._options["power_entity"] = user_input.get("power_entity", "")
                return await self._finish({"deployment": "external", "api_url": url})
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="external",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "api_url",
                        default=defaults.get("api_url", "http://localhost:8099"),
                    ): str,
                    power_key(
                        self._editing.options.get("power_entity", "")
                        if self._editing
                        else ""
                    ): power_field(),
                }
            ),
            errors=errors,
            description_placeholders={
                "serial": str(defaults.get("charger_serial", "")),
                "energy_wh": str(defaults.get("initial_energy_wh", 0)),
            },
        )

    async def _finish(self, data):
        if self._editing is not None:
            return self.async_update_reload_and_abort(
                self._editing, data=data, options=self._options
            )
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="OCPP Charge Proxy", data=data, options=self._options
        )

    async def async_step_reconfigure(self, user_input=None):
        self._editing = self._get_reconfigure_entry()
        self._options = dict(self._editing.options)
        return await self.async_step_user(user_input)

    async def async_step_hassio(self, discovery_info):
        existing = self._async_current_entries()
        if existing and deployment(existing[0].data) == "native":
            return self.async_abort(reason="already_configured")
        host = discovery_info.config.get("host", "")
        port = discovery_info.config.get("port", 8099)
        self._discovered_url = f"http://{host}:{port}"
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured(updates={"api_url": self._discovered_url})
        if not await _try_connect(self.hass, self._discovered_url):
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(self, user_input=None):
        if user_input is not None:
            self._options = {"power_entity": user_input.get("power_entity", "")}
            return await self._finish(
                {"deployment": "external", "api_url": self._discovered_url}
            )
        return self.async_show_form(
            step_id="hassio_confirm",
            data_schema=vol.Schema({vol.Optional("power_entity"): power_field()}),
            description_placeholders={"url": self._discovered_url},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OCPPChargeProxyOptionsFlow()


class OCPPChargeProxyOptionsFlow(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    power_key(
                        self.config_entry.options.get("power_entity", "")
                    ): power_field()
                }
            ),
        )
