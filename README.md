# OCPP Charge Proxy for Home Assistant

One custom integration, configured in Home Assistant. No MQTT broker, separate app
or companion installation is required for normal use.

| Mode | What runs in Core |
|------|-------------------|
| Emulator | A virtual single-phase OCPP 1.6J chargepoint connecting to a provider |
| Transparent relay | An authenticated listener forwarding the real charger's messages to its provider |

The integration includes its protocol engine, native sensors/controls, configuration
flow, persistent energy/identity storage and redacted relay diagnostics. The default
installation runs inside Core; an external standalone connection remains optional.

## Install

Requires Home Assistant **2026.11.1 or later**. The test baseline is 2026.11.1.

1. Add `https://github.com/abedegno/home-assistant-ocpp-proxy` as a custom
   **integration** repository in Marketplace/HACS, then install **OCPP Charge Proxy**.
   This does not imply it is already listed in the community catalog.
2. Restart Home Assistant Core.
3. Open **Settings → Devices & Services → Add Integration → OCPP Charge Proxy**.
4. Choose **Run in Home Assistant**, enter the provider credentials and select a mode.
5. Configure the relay listener or the virtual charger identity in the next step.

Manual installation copies `custom_components/ocpp_charge_proxy` into the matching
folder under `/config/custom_components/`, followed by a Core restart. All required
code is inside that folder; dependencies are declared in its manifest.

Use a released version. A development branch or draft PR is not a released upgrade.

## Prerequisites and behavior

Both modes require OCPP provider credentials: server host, chargepoint ID and Basic
password. A consumer API integration does not necessarily expose these credentials.
Relay use also requires permission/access to edit the charger's OCPP endpoint.
Compatibility with every provider/charger is not implied.

**Core restarts or integration reloads disconnect the native proxy.** The charger
must reconnect when the listener returns. Closing a relay connection does not revoke
an already accepted charger schedule or guarantee charging stops. See [relay setup
and rollback](RELAY.md) before using it with a real charger.

Emulator mode exposes virtual charging state for separate automations. It does not
control a real charger by itself. Estimated energy is not a billing measurement.
Absolute/Relative single-phase profiles are supported; recurring/multiphase profiles
are rejected. Profile transitions are evaluated during meter sampling.

## Configuration and entities

Use **Reconfigure** on the integration to change provider credentials, operating
mode, deployment or listener settings. Options selects the optional emulator power
sensor. Supported HA power units are converted to kW; unavailable/invalid values
clear the override and restore simulation. Relay mode ignores the power input.

Existing sensors and controls retain entry-based unique IDs:

| Entity | Emulator | Relay |
|--------|----------|-------|
| State | Virtual connector state | Observed connector-1 state |
| Power / Current | Simulation or capped HA power input | Observed aggregate measurements |
| Energy | Persistent estimated import register | Observed import register |
| Power Source | `simulated` / `entity` | `wallbox` |
| Connected to Server | Provider connected | Provider connected |
| Plugged In switch | Virtual plug/unplug | Unavailable |
| Current Amps selector | Virtual current setting | Unavailable |

Native operation opens no HTTP control API. The relay port is configured separately
(default 9000). Container installations of Core may need to expose that port.

## Existing users and optional standalone deployment

Existing companion configuration entries remain **external** after upgrading; the
integration never silently starts another connection with the same identity.
Reconfigure that same entry to move into Core while preserving entity IDs. Read
[the migration guide](MIGRATION.md) first to preserve serial and energy continuity.

For independence from Core restarts, use the optional [standalone container](standalone/README.md)
or the [separate HA app project](https://github.com/abedegno/ocpp_charge_proxy).
Those are advanced alternatives, not prerequisites. Choose **Connect to standalone
proxy** to use its private API. Stop the previous runtime before starting a replacement.

## Diagnostics, storage and privacy

Download integration diagnostics for redacted state and recent relay records.
Persistent files live under `/config/ocpp_charge_proxy/<entry_id>/`; relay JSONL
captures are in its `relay/` subdirectory. Writes and certificate/file loading run
off Core's event loop. Unload closes sockets and flushes the single persistence writer.
Persistence failures appear in diagnostics and prevent a false successful handoff;
repair storage before retrying. Offline startup retains the stored register.

Captures still contain device/session metadata. Check `log_dropped` and `log_error`
for gaps and review before sharing. Never expose the optional standalone HTTP API
to the internet; it has no independent authentication.

- [Migration](MIGRATION.md)
- [Relay setup and limitations](RELAY.md)
- [Contributing, tests and packaging](CONTRIBUTING.md)
- [Change history](CHANGELOG.md)
- [MIT license](LICENSE.md)
