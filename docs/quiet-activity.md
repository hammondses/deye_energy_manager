# Quiet Deye Activity without losing history

On 2026-09-12 a complete one-hour Activity query returned 420 Deye Energy Manager entries. Seven diagnostic sensors accounted for 390 (93%): SOC age 120; solar-arrived reason 58; paid-time reserve reason 58; energy-budget reason 56; energy-plan reason 50; cooling calibration state 30; cooling reason 18.

The integration's effective system-log level was already WARNING. The observed flood is entity state changes in Activity/Logbook, not Python debug logging. Changing the logger level would not solve it.

Use Home Assistant's native [Activity exclusion filter](https://www.home-assistant.io/integrations/logbook/). Merge this into `configuration.yaml` (merge the list if a `logbook:` section already exists; never duplicate the top-level key):

```yaml
# Hide high-frequency Deye diagnostics from Activity; keep history and control events.
logbook:
  exclude:
    entity_globs:
      - sensor.*deye_energy_manager_taycan_soc_age_minutes
      - sensor.*deye_energy_manager_solar_arrived_reason
      - sensor.*deye_energy_manager_paid_time_reserve_reason
      - sensor.*deye_energy_manager_energy_budget_reason
      - sensor.*deye_energy_manager_energy_plan_reason
      - sensor.*deye_energy_manager_cooling_calibration_state
      - sensor.*deye_energy_manager_cooling_reason
```

The wildcard accommodates both original and area-prefixed entity IDs. If entities are manually renamed outside this pattern, use their actual IDs.

This hides routine diagnostic updates from Activity while retaining live sensor states, automations, and recorder history. It leaves control actions, switches, settings, tariff changes, bedroom/EV state and cooling protection/health visible. It does not purge existing records or change logger/recorder settings. It does not reduce database storage; that is a separate decision about historical data retention.

Check Home Assistant configuration before restarting to load the filter. Undo by removing these seven exclusions and restarting again. There is an [upstream report about explicitly entity/device-scoped Activity views ignoring exclusions](https://github.com/home-assistant/core/issues/177929); verify the default Activity feed as well as the view in use.

The 93% figure is the fraction covered in the sampled hour, not a guaranteed future rate reduction. No integration release or actuator change is required.
