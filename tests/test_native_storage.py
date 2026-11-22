"""Native persistence must never block Core or leave stale writers behind."""

import asyncio
import json
import threading

import pytest


@pytest.mark.asyncio
async def test_storage_is_serialized_off_loop_and_flushed(tmp_path, monkeypatch):
    from custom_components.ocpp_charge_proxy.storage import AsyncPersistence
    from custom_components.ocpp_charge_proxy.engine.persistence import Persistence

    original = Persistence.save_energy_register_wh
    threads = []

    def save(self, value):
        threads.append(threading.get_ident())
        original(self, value)

    monkeypatch.setattr(Persistence, "save_energy_register_wh", save)
    storage = await AsyncPersistence.async_open(
        tmp_path, initial_energy_wh=5000, serial="EXISTING"
    )
    assert storage.load_energy_register_wh() == 5000
    assert storage.load_serial_number() == "EXISTING"
    storage.save_energy_register_wh(6000)
    storage.save_energy_register_wh(7000)
    await storage.async_close()
    assert (
        json.loads((tmp_path / "energy_register.json").read_text())["energy_wh"] == 7000
    )
    assert threads and all(ident != threading.get_ident() for ident in threads)
    with pytest.raises(RuntimeError):
        storage.save_energy_register_wh(8000)
    reloaded = await AsyncPersistence.async_open(
        tmp_path, initial_energy_wh=1, serial="OTHER"
    )
    assert (
        reloaded.load_energy_register_wh() == 7000
        and reloaded.load_serial_number() == "EXISTING"
    )
    await reloaded.async_close()


@pytest.mark.asyncio
async def test_explicit_handoff_applies_once_after_external_run(tmp_path):
    from custom_components.ocpp_charge_proxy.storage import AsyncPersistence

    first = await AsyncPersistence.async_open(
        tmp_path, initial_energy_wh=5000, serial="ORIGINAL"
    )
    await first.async_close()
    handed = await AsyncPersistence.async_open(
        tmp_path,
        initial_energy_wh=9000,
        serial="SAME-PROVIDER",
        handoff_token="switch-1",
    )
    assert (
        handed.load_energy_register_wh() == 9000
        and handed.load_serial_number() == "SAME-PROVIDER"
    )
    handed.save_energy_register_wh(10000)
    await handed.async_close()
    again = await AsyncPersistence.async_open(
        tmp_path,
        initial_energy_wh=9000,
        serial="SAME-PROVIDER",
        handoff_token="switch-1",
    )
    assert again.load_energy_register_wh() == 10000
    await again.async_close()
