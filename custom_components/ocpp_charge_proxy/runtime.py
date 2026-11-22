"""Entry-owned proxy runtime. No environment, signal or process-wide setup."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import logging
import ssl
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError

from .engine import transport
from .engine.async_io import offload
from .engine.__main__ import run_emulator_session
from .engine.charger_sim import VALID_CURRENT_SETTINGS
from .engine.client import ChargePoint, RegistrationRejected
from .engine.relay import RelayServer, TrafficLog
from .engine.shared_state import SharedState
from .storage import AsyncPersistence

_LOGGER = logging.getLogger(__name__)


class NativeRuntime:
    RETRY_STEPS = (5, 10, 30, 60, 300)

    def __init__(self, hass, entry, config):
        self.hass, self.entry, self.config = hass, entry, config
        self.state = SharedState(state="Unavailable", mode=config.mode)
        self.directory = Path(hass.config.path("ocpp_charge_proxy", entry.entry_id))
        self.cp = self.relay = self.audit = self.persistence = None
        self.last_error = None
        self.ssl_context = None
        self._task = None
        self._stopped = False
        self._stop_lock = asyncio.Lock()
        self._resources = AsyncExitStack()
        self._power_override = None
        self._current_amps = config.current_amps
        self._transport_logger = logging.getLogger(__name__ + ".transport")
        self._transport_logger.setLevel(logging.CRITICAL)

    async def async_start(self):
        try:
            if self.config.mode == "relay":
                self.audit = await self._resources.enter_async_context(
                    TrafficLog(self.directory / "relay", self.state)
                )
                self.relay = await self._resources.enter_async_context(
                    RelayServer(self.config, self.state, self.audit)
                )
            else:
                self.persistence = await AsyncPersistence.async_open(
                    self.directory,
                    self.config.initial_energy_wh,
                    self.config.charger_serial,
                    self.entry.data.get("handoff_token"),
                )
                self._resources.push_async_callback(self.persistence.async_close)
                self.state.energy_kwh = (
                    self.persistence.load_energy_register_wh() / 1000
                )
                self.state.current_amps_setting = self._current_amps
                if self.config.use_tls:
                    self.ssl_context = await offload(ssl.create_default_context)
                self._task = self.entry.async_create_background_task(
                    self.hass, self._emulator_loop(), "OCPP Charge Proxy emulator"
                )
        except BaseException:
            await self.async_stop()
            raise

    async def _emulator_loop(self):
        attempt = 0
        try:
            while True:
                try:
                    async with transport.connect(
                        self.config.websocket_url,
                        subprotocols=["ocpp1.6"],
                        logger=self._transport_logger,
                        open_timeout=15,
                        close_timeout=3,
                        ssl=self.ssl_context,
                    ) as socket:
                        self.cp = ChargePoint(
                            self.config.chargepoint_id,
                            socket,
                            self.persistence,
                            current_amps=self._current_amps,
                            shared_state=self.state,
                        )
                        self.cp._power_override = self._power_override
                        self.last_error = None
                        await run_emulator_session(
                            self.cp, self.config, self.persistence
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if self.cp is not None and self.cp._registered:
                        attempt = 0
                    self.last_error = (
                        "Provider registration rejected"
                        if isinstance(error, RegistrationRejected)
                        else "Provider connection unavailable"
                    )
                    _LOGGER.warning("%s; retrying", self.last_error)
                finally:
                    self.cp = None
                    self.state.connected_to_server = False
                    self.state.state = "Unavailable"
                delay = self.RETRY_STEPS[min(attempt, len(self.RETRY_STEPS) - 1)]
                attempt += 1
                await asyncio.sleep(delay)
        finally:
            self.state.connected_to_server = False
            self.state.state = "Unavailable"

    async def async_stop(self):
        async with self._stop_lock:
            if self._stopped:
                if self.persistence is not None and self.persistence.last_error:
                    await self.persistence.async_close()
                return
            self._stopped = True
            try:
                if self._task is not None:
                    self._task.cancel()
                    await asyncio.gather(self._task, return_exceptions=True)
            finally:
                await self._resources.aclose()
                self.cp = None
                self.state.connected_to_server = False
                self.state.state = "Unavailable"

    def snapshot(self):
        return {
            **self.state.to_dict(),
            "deployment": "native",
            "last_error": self.last_error,
            "persistence_error": self.persistence.last_error
            if self.persistence is not None
            else None,
        }

    async def async_command(self, endpoint, body=None):
        if self.config.mode == "relay":
            raise HomeAssistantError("Relay mode is read-only")
        if self._stopped:
            raise HomeAssistantError("Proxy is stopped")
        body = body or {}
        if endpoint == "/api/power":
            self._power_override = body.get("power_kw")
            if self.cp is not None:
                self.cp._power_override = self._power_override
            return
        if endpoint == "/api/current":
            amps = body.get("amps")
            if type(amps) is not int or amps not in VALID_CURRENT_SETTINGS:
                raise HomeAssistantError("Unsupported current")
            self._current_amps = amps
            self.state.current_amps_setting = amps
            if self.cp is not None:
                self.cp._charger_sim.current_amps = amps
            return
        if self.cp is None or not self.state.connected_to_server:
            raise HomeAssistantError("Provider is not connected")
        cp = self.cp
        if endpoint == "/api/plug":
            if self.state.plugged_in:
                return
            cp.state = "Preparing"
            self.state.state, self.state.plugged_in = cp.state, True
            await cp.send_status()
        elif endpoint == "/api/unplug":
            cp.invalidate_pending_start()
            self.state.plugged_in = False
            self.state.state = "Available"
            if cp._transaction_id is not None:
                await cp._do_stop_transaction(final_state="Available")
            cp.state = "Available"
            self.state.state = cp.state
            await cp.send_status()
        else:
            raise HomeAssistantError("Unsupported proxy command")
