"""Independent review regressions: continuity, durable handoff and cancellation."""

import asyncio
import base64
import json
from pathlib import Path
import ssl
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from .test_companion import hass, entry
from .test_native_runtime import config
from .test_native_setup import make_entry
from custom_components.ocpp_charge_proxy.engine import transport as ws
from custom_components.ocpp_charge_proxy.engine.persistence import Persistence
from custom_components.ocpp_charge_proxy.runtime import NativeRuntime
from custom_components.ocpp_charge_proxy.storage import AsyncPersistence


@pytest.mark.asyncio
async def test_first_offline_snapshot_preserves_saved_register(hass, monkeypatch):
    async def idle(self):
        await asyncio.Future()

    monkeypatch.setattr(NativeRuntime, "_emulator_loop", idle)
    runtime = NativeRuntime(
        hass, entry(), config(current_amps=16, initial_energy_wh=8123)
    )
    await runtime.async_start()
    try:
        assert runtime.snapshot()["energy_kwh"] == 8.123
        assert runtime.snapshot()["current_amps_setting"] == 16
    finally:
        await runtime.async_stop()


@pytest.mark.asyncio
async def test_failed_handoff_does_not_commit_token(tmp_path, monkeypatch):
    original = await AsyncPersistence.async_open(tmp_path, 2000, "ORIGINAL")
    await original.async_close()
    import os

    replace = os.replace

    def fail(source, destination):
        if Path(destination).name == "energy_register.json":
            raise OSError("disk failure")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail)
    broken = None
    try:
        with pytest.raises(OSError):
            broken = await AsyncPersistence.async_open(
                tmp_path, 9000, "SAME", handoff_token="handoff"
            )
    finally:
        if broken:
            await broken.async_close()
    monkeypatch.setattr(os, "replace", replace)
    recovered = await AsyncPersistence.async_open(
        tmp_path, 9000, "SAME", handoff_token="handoff"
    )
    assert recovered.load_energy_register_wh() == 9000
    await recovered.async_close()


@pytest.mark.asyncio
async def test_dirty_write_failure_is_visible_and_close_can_retry(
    tmp_path, monkeypatch
):
    storage = await AsyncPersistence.async_open(tmp_path, 5000, "SAME")
    save = storage.store.save_energy_register_wh

    def fail(value):
        raise OSError("disk failure")

    monkeypatch.setattr(storage.store, "save_energy_register_wh", fail)
    storage.save_energy_register_wh(6000)
    try:
        async with asyncio.timeout(1):
            while (
                not getattr(storage, "last_error", None) and not storage._worker.done()
            ):
                await asyncio.sleep(0.001)
        assert storage.last_error
        with pytest.raises(OSError):
            await storage.async_close()
    finally:
        monkeypatch.setattr(storage.store, "save_energy_register_wh", save)
        await storage.async_close()
    assert (
        json.loads((tmp_path / "energy_register.json").read_text())["energy_wh"] == 6000
    )
    assert storage.last_error is None


@pytest.mark.asyncio
async def test_cancelled_open_joins_old_file_work_before_replacement(
    tmp_path, monkeypatch
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    save = Persistence.save_energy_register_wh

    def slow(self, value):
        if value == 100:
            started.set()
            release.wait(2)
        try:
            save(self, value)
        finally:
            if value == 100:
                finished.set()

    monkeypatch.setattr(Persistence, "save_energy_register_wh", slow)
    opening = asyncio.create_task(AsyncPersistence.async_open(tmp_path, 100, "OLD"))
    assert await asyncio.to_thread(started.wait, 1)
    opening.cancel()
    await asyncio.sleep(0.01)
    completed_early = opening.done()
    release.set()
    await asyncio.gather(opening, return_exceptions=True)
    await asyncio.to_thread(finished.wait, 1)
    assert not completed_early
    replacement = await AsyncPersistence.async_open(
        tmp_path, 8000, "NEW", handoff_token="replacement"
    )
    await replacement.async_close()
    assert (
        json.loads((tmp_path / "energy_register.json").read_text())["energy_wh"] == 8000
    )


@pytest.mark.asyncio
async def test_cancelled_audit_setup_closes_opened_handler(tmp_path, monkeypatch):
    from custom_components.ocpp_charge_proxy.engine.relay import (
        TrafficLog,
        StrictFileHandler,
    )
    from custom_components.ocpp_charge_proxy.engine.shared_state import SharedState

    started, release = threading.Event(), threading.Event()
    original = StrictFileHandler.__init__

    def slow(self, *args, **kwargs):
        original(self, *args, **kwargs)
        started.set()
        release.wait(2)

    monkeypatch.setattr(StrictFileHandler, "__init__", slow)
    audit = TrafficLog(tmp_path, SharedState())
    opening = asyncio.create_task(audit.__aenter__())
    assert await asyncio.to_thread(started.wait, 1)
    opening.cancel()
    await asyncio.sleep(0.01)
    completed_early = opening.done()
    release.set()
    await asyncio.gather(opening, return_exceptions=True)
    async with asyncio.timeout(1):
        while not hasattr(audit, "handler"):
            await asyncio.sleep(0.001)
    try:
        assert not completed_early
        assert audit.handler.stream is None
    finally:
        await asyncio.to_thread(audit.handler.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["emulator", "relay"])
async def test_upstream_tls_context_is_verified_and_loaded_off_loop(
    hass, monkeypatch, mode
):
    threads = []
    original_context = ssl.create_default_context

    def context(*args, **kwargs):
        threads.append(threading.get_ident())
        return original_context(*args, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", context)
    captures = []
    connect = ws.connect

    def spy(url, *args, **kwargs):
        if url.startswith("wss://"):
            captures.append(kwargs)
        return connect(url, *args, **kwargs)

    monkeypatch.setattr(ws, "connect", spy)
    server = await asyncio.start_server(
        lambda reader, writer: writer.close(), "127.0.0.1", 0
    )
    runtime = NativeRuntime(
        hass,
        entry(),
        config(
            mode=mode,
            use_tls=True,
            server_hostname=f"127.0.0.1:{server.sockets[0].getsockname()[1]}",
        ),
    )
    car = None
    try:
        await runtime.async_start()
        if mode == "relay":
            token = base64.b64encode(b"CP001:test-secret").decode()
            car = await ws.connect(
                runtime.relay.url,
                subprotocols=["ocpp1.6"],
                extra_headers={"Authorization": "Basic " + token},
            )
        async with asyncio.timeout(2):
            while not captures:
                await asyncio.sleep(0.001)
        assert captures[0].get("ssl") is not None
        assert (
            captures[0]["ssl"].verify_mode == ssl.CERT_REQUIRED
            and captures[0]["ssl"].check_hostname
        )
        assert threads and all(ident != threading.get_ident() for ident in threads)
    finally:
        await runtime.async_stop()
        if car:
            await car.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_retry_handoff_after_cancel_reads_persisted_snapshot(hass):
    from custom_components.ocpp_charge_proxy.config_flow import (
        OCPPChargeProxyConfigFlow,
    )

    entry = make_entry(
        {
            "deployment": "native",
            "mode": "emulator",
            "charger_serial": "",
            "initial_energy_wh": 1000,
        }
    )
    directory = Path(hass.config.path("ocpp_charge_proxy", entry.entry_id))

    def write():
        directory.mkdir(parents=True)
        store = Persistence(str(directory))
        store.save_energy_register_wh(9999)
        store.save_serial_number("123456")

    await asyncio.to_thread(write)
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_known_entry.return_value = entry
    hass.config_entries.async_unload = AsyncMock(return_value=True)
    flow = OCPPChargeProxyConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    await flow.async_step_reconfigure({"deployment": "external"})
    result = await flow.async_step_stop_native({"confirm_stop": True})
    assert result["description_placeholders"] == {
        "serial": "123456",
        "energy_wh": "9999",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("registered,expected", [(True, [1, 1]), (False, [1, 2])])
async def test_reconnect_backoff_resets_only_after_registration(
    hass, monkeypatch, registered, expected
):
    import custom_components.ocpp_charge_proxy.runtime as module

    runtime = NativeRuntime(hass, entry(), config())
    runtime.RETRY_STEPS = (1, 2, 3)
    delays = []

    class Connection:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            pass

    async def delay(value):
        delays.append(value)
        if len(delays) == 2:
            raise asyncio.CancelledError

    async def failed_session(*args):
        raise OSError("session ended")

    monkeypatch.setattr(
        module.transport, "connect", lambda *args, **kwargs: Connection()
    )
    monkeypatch.setattr(
        module,
        "ChargePoint",
        lambda *args, **kwargs: SimpleNamespace(_registered=registered),
    )
    monkeypatch.setattr(module, "run_emulator_session", failed_session)
    monkeypatch.setattr(
        module,
        "asyncio",
        SimpleNamespace(sleep=delay, CancelledError=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        await runtime._emulator_loop()
    assert delays == expected
