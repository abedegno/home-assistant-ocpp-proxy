# Moving between deployments

Version 0.3 adds native operation. Version-1 companion entries migrate to configuration
version 2 **without changing backend**. Their API URL, options and entry ID remain;
Core does not start a second proxy. Optional-app discovery cannot overwrite a native
entry's configuration.

## Standalone emulator → native

1. Record the provider host/ID/password, model/vendor/firmware, existing **serial**
   and latest energy register. The integration pre-fills its last reported energy
   when available; verify that against the standalone register, especially if it
   was still charging after the last poll.
2. Stop the standalone emulator. Do not run two copies with the same provider ID.
3. Use **Reconfigure** on the existing integration entry. Choose **Run in Home
   Assistant**, emulator mode and the same provider credentials.
4. Copy the original serial and register in Wh into the identity step. Migration
   requires an explicit serial; it does not silently generate a replacement.
5. Save and check connection, state, identity and energy before using automations.

The handoff seeds native files once. Later reloads/restarts retain accumulated
energy instead of reapplying that seed. A migration never lowers a previously
stored native register, preserving cumulative statistics. Existing entry-based
entity IDs survive; do not delete/re-add the integration to migrate.

## Standalone relay → native

Save the charger's full original endpoint and authentication. Stop the standalone
relay, reconfigure the same integration entry to native relay, and adjust the
charger endpoint if its host/port changed. The real charger supplies its identity
and meter readings; virtual serial/register seeds do not apply. Check the real
BootNotification and scheduling responses before a supervised charge.

## Native → standalone

Use Reconfigure and choose the standalone deployment. The flow asks you to stop
the native runtime before you start a replacement. Confirming unloads this integration
and flushes its final register; the next form shows its serial and register. Seed
and configure the standalone copy with those values, start it, then enter its API URL.
Native files remain available for a later return.

If you cancel after stopping, reload the integration to resume native operation.
Finish the handoff before restarting Core, since the saved backend remains native
until the flow completes. If the integration cannot unload, the flow stops rather
than encouraging a second connection. Verify that only one runtime is active.

For relay rollback, stop/unload the native relay and restore the charger's saved
direct endpoint/settings, or restore its standalone relay endpoint and start that
copy. Accepted offline schedules may continue during any interruption; disconnecting
the proxy does not guarantee charging stops.

## Scope

A Core restart/reload necessarily interrupts native connections. Choose standalone
operation if Core-independent continuity matters. Backend changes do not transfer
private files automatically between containers; the UI's explicit serial/register
handoff and these checks prevent hidden identity changes. No installed app,
automation or charger endpoint is modified automatically by this integration.
