# Development and verification

## Layout

- `custom_components/ocpp_charge_proxy/`: complete installable integration.
- `engine/` inside it: neutral protocol engine and optional standalone CLI.
- `runtime.py` / `storage.py`: entry-owned runtime and ordered off-loop persistence.
- `config_flow.py`: native/external setup, reconfigure and discovery guard.
- `tests/engine/`: retained protocol, API, accounting, scheduling and socket regressions.
- Other `tests/`: actual HA classes, native lifecycle, migration and isolated install.
- `standalone/`: optional plain Docker packaging, not HA OS app metadata.

The public integration repository must contain no HA OS app configuration. The
optional HA app stays in its existing separate repository. This keeps Marketplace
installation independent of Supervisor and brokers.

## Run tests

Use Python 3.14.2+, Home Assistant 2026.11.1 and OpenSSL for TLS fixtures:

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest tests -q --cov=custom_components.ocpp_charge_proxy --cov-branch --cov-report=term-missing
```

Tests bind local loopback sockets and start simulated providers only. The isolated
installation test copies just the component into a fresh config directory and uses
HA's real loader/config-flow manager. It does not boot a complete HA OS/Supervisor
installation or contact a real provider.

The engine targets ocpp2.1.0 and websockets17.4. Its explicit legacy transport API
preserves the current engine interface on the modern installed library; that API
is deprecated upstream and will need a later transport migration. Avoid reverting
to a websocket13 pin inside Core or mutating third-party module globals.

Use entry-owned HA background tasks for permanent provider loops. Never call
`asyncio.run`, install signal handlers, read process configuration or change global
logging settings during native setup. File reads, fsync/writes, log handler setup
and TLS loading must stay off the event loop. One writer per entry must flush before
replacement startup. Do not downgrade a legacy entry into native operation automatically.

## Packaging and CI

`manifest.json` declares engine dependencies; everything else needed by the
integration must remain inside its component directory. Never import standalone
source from outside that directory. Keep `strings.json` and English translations
in sync. Version 0.3.0 is the prepared native release.

CI runs all tests/coverage, hassfest/HACS validation and builds the optional Docker
image. The combined line/branch floor is 70%. Inspect remaining gaps rather than
adding tests that merely restate code. Run actionlint and local document-link checks
before publishing changes. The component's brand icon is inherited from the original
project; no claim of Home Assistant certification is implied.

Before release, obtain independent review and verify a disposable real installation,
including reload/shutdown, upgrades, optional external entries and the expected
Core-restart interruption. Real provider/charger interoperability needs supervised
validation. Preserve endpoint/authentication for rollback; never change a live
installation as part of automated tests.
