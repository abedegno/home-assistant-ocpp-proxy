"""Cached synchronous protocol interface with one off-loop persistent writer."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .engine.persistence import Persistence
from .engine.async_io import offload
import json


class AsyncPersistence:
    def __init__(self, store, energy, serial):
        self.store = store
        self.energy = energy
        self.serial = serial
        self._pending = None
        self._dirty = asyncio.Event()
        self._closing = False
        self._closing_event = asyncio.Event()
        self.last_error = None
        self._worker = asyncio.create_task(self._write())

    @classmethod
    async def async_open(
        cls, directory, initial_energy_wh=0, serial="", handoff_token=None
    ):
        def load():
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            store = Persistence(str(path), strict=True)
            if (
                handoff_token
                and store._read("handoff.json", "token", None) != handoff_token
            ):
                # A deliberate backend switch seeds exactly once, after the old writer stopped.
                store.save_energy_register_wh(
                    max(store.load_energy_register_wh(), initial_energy_wh)
                )
                if serial:
                    store.save_serial_number(serial)
                store._write("handoff.json", "token", handoff_token)
            if not (path / "energy_register.json").exists():
                store.save_energy_register_wh(initial_energy_wh)
            if serial and not (path / "serial_number.json").exists():
                store.save_serial_number(serial)
            return store, store.load_energy_register_wh(), store.load_serial_number()

        return cls(*await offload(load))

    def load_energy_register_wh(self):
        return self.energy

    def load_serial_number(self):
        return self.serial

    def save_energy_register_wh(self, value):
        if self._closing:
            raise RuntimeError("Persistence is closed")
        self.energy = value
        self._pending = value
        self._dirty.set()

    async def _write(self):
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            value, self._pending = self._pending, None
            if value is not None:
                try:
                    await offload(self.store.save_energy_register_wh, value)
                except OSError:
                    self.last_error = "Unable to persist the energy register"
                    self._pending = self.energy
                    self._dirty.set()
                    if self._closing:
                        raise
                    try:
                        await asyncio.wait_for(self._closing_event.wait(), timeout=5)
                    except TimeoutError:
                        pass
                    continue
                self.last_error = None
            if self._closing and self._pending is None:
                return

    async def async_close(self):
        self._closing = True
        self._closing_event.set()
        self._dirty.set()
        if (
            self._worker.done()
            and not self._worker.cancelled()
            and self._worker.exception() is not None
        ):
            # A failed final flush is retryable after storage is repaired.
            await offload(self.store.save_energy_register_wh, self.energy)
            self.last_error = None
            return
        await self._worker

    @staticmethod
    async def async_read_snapshot(directory, serial=""):
        def read():
            path = Path(directory)
            with (path / "energy_register.json").open() as stream:
                energy = json.load(stream)["energy_wh"]
            if type(energy) is not int or energy < 0:
                raise ValueError("Invalid saved energy register")
            identity = serial
            if not identity:
                with (path / "serial_number.json").open() as stream:
                    identity = json.load(stream)["serial"]
            if not isinstance(identity, str) or not identity:
                raise ValueError("No saved serial number")
            return {"charger_serial": identity, "initial_energy_wh": energy}

        return await offload(read)
