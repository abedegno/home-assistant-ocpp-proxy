"""Load the integration from a clean config directory without app/repo code."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_integration_only_install_and_real_config_flow(tmp_path):
    source = (
        Path(__file__).resolve().parents[1] / "custom_components" / "ocpp_charge_proxy"
    )
    destination = tmp_path / "custom_components" / "ocpp_charge_proxy"
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__"))
    script = r"""
import asyncio,json
from pathlib import Path
from homeassistant.core import HomeAssistant
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
async def run():
    manifest=json.loads(Path('custom_components/ocpp_charge_proxy/manifest.json').read_text())
    assert 'ocpp==2.1.0' in manifest['requirements']
    from custom_components.ocpp_charge_proxy.engine.client import ChargePoint
    assert str(Path(ChargePoint.__module__.replace('.','/')).parent).startswith('custom_components')
    hass=HomeAssistant(str(Path.cwd()))
    loader.async_setup(hass)
    hass.config_entries=ConfigEntries(hass,{})
    await hass.config_entries.async_initialize()
    try:
        result=await hass.config_entries.flow.async_init('ocpp_charge_proxy',context={'source':'user'})
        assert result['step_id']=='user',result
        result=await hass.config_entries.flow.async_configure(result['flow_id'],{'deployment':'native'})
        assert result['step_id']=='native',result
        result=await hass.config_entries.flow.async_configure(result['flow_id'],{
            'mode':'relay','server_hostname':'provider.invalid','chargepoint_id':'TEST','password':'private'})
        assert result['step_id']=='relay',result
        hass.config_entries.flow.async_abort(result['flow_id'])
    finally:
        await hass.async_stop(force=True)
    print('ISOLATED_INSTALL_OK')
asyncio.run(run())
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONPATH", "PYTEST_ADDOPTS")
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "ISOLATED_INSTALL_OK" in result.stdout
