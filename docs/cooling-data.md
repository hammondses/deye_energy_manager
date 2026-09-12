# Cooling observations: collection and first-week review

Implemented on 13 September 2026 in v0.6.0b8 on `overhaul`, including b7's
receipt-identity and fine-grained fan-control fixes. Deployment/start time must
be verified from the collection status sensor; a Git commit alone does not start
the observation week. Review approximately seven days after collection starts.

## Collection

The integration reads existing HA states every 15 seconds on a separate timer.
It creates time-weighted five-minute UTC windows in memory, then writes one row
to `/config/deye_energy_manager_data/<entry_id>/YYYY-MM-DD.jsonl.gz` off the HA
event loop. There are 288 full windows per day. Only files older than 90 days in
this dedicated directory are removed. No database, extra MQTT subscription,
sensor-history join, per-reading log message or automated fan experiment is used.

`Cooling data collection enabled` is an independent live switch (default on).
Turning it off discards the unfinished window; it changes no actuator gate.
`Cooling data collection` reports starting/collecting/disabled/write_error, with
last saved window, directory, windows written and write failures in attributes.
Counts are since integration startup. An error is logged once per failure run;
failed windows are not silently reported as saved. The current partial window
can be lost on restart; resumed windows expose their reduced coverage.

Summaries use held samples for at most 30 seconds. Larger gaps are missing, not
zero, and no empty rows are invented for downtime. Each field has weighted mean,
min, max, first/last observed value, delta, covered seconds and coverage fraction.
Power fields also have Wh. First/last are observations within the window, not
interpolated values at the exact edges. Source ages are recorded separately.
Unavailable/nonfinite values are omitted. Electrical/thermal/RPM readings older
than 120 seconds are omitted; ambient/humidity/SOC use 3600 seconds. The existing
cooling stale-temperature test is also captured as a flag. These limits describe
data quality, not control thresholds. Slow sensors can legitimately have old
unchanged readings: inspect age and coverage before treating a gap as a fault.

## Fields and interpretation

- PV power, signed inverter AC power, signed battery power, external-CT grid
  power, essential/nonessential load, and raw reported load power.
- Battery positive = discharge; CT grid positive = import, following the current
  Sunsynk mappings. Charge/discharge and import/export are split before averaging
  and integration, so reversals do not cancel. Recheck signs after remapping.
- Grid voltage/current, inverter AC current, battery voltage/current and SOC.
  Conditional voltage/current summaries separate import (>50 W), export (<−50 W)
  and near-idle; this 50 W classification only filters directional noise, it does
  not discard energy from the directional totals.
- AC/DC temperatures, garage temperature/humidity, temperature above ambient,
  AC trend, actual fan percentage, RPM and fan-change count.
- Temperature-invalid, recovery, protection, fan-health failure, control-disabled
  and control-blocked duration; controller version, cooling settings and entity
  mappings. `context_changed` marks a window crossing a setting/mapping change.

House power is essential + nonessential. `input_w` is PV + battery discharge +
grid import; `output_w` is house + battery charge + export. These are site energy
balances, not a claim that all grid/house power traverses the inverter. Neither
input + output nor max(channel) is labelled total physical inverter throughput.
`balance_w` is input − output: it includes losses, timing skew and sensor errors;
it is not a measured efficiency or heat-loss value.

Destination percentages use integrated energy from simultaneously valid flow
samples, normalised across battery charging, house and export. For 12 kW PV,
4.8 kW charge, 1.2 kW house and 6 kW export, this is 40/10/50%. They describe
destinations, not exact PV provenance when import or battery discharge contributes.
All raw signed channels, directional Wh and coverage remain available.

Initial inspection found the raw `sensor.deye_load_power` around 99 W while
essential power was around 993 W. Grid current also implied apparent power far
larger than the near-zero CT active power. Retain these raw measurements for
investigation; do not infer power factor or correct scaling without verification.
The garage sensor is an ambient proxy, not a verified inlet-air measurement.

## Review after one week

Copy the dedicated directory over the existing SMB config share, then run:

```sh
python3 tools/review_cooling_data.py /path/to/entry_id --days 7 --csv /tmp/cooling-week.csv
```

This produces coverage, operating ranges, version and safety-flag counts plus
an optional flattened CSV. No credentials or dataset belong in Git. Keep analysis
notes here (or an adjacent dated Markdown file), with the collection dates,
version, settings, exclusions and number of usable windows.

1. Verify collection coverage, power signs/scales, fan response and balance errors.
2. Separate firmware/settings periods and flag partial, stale, recovery and
   protection windows. Fan-health failure while fans are intentionally off is not
   itself evidence of failed hardware.
3. Compare steady windows separately from load/fan transitions. Start with low
   fan/load variability and small temperature delta; state the chosen cutoffs.
4. Join preceding windows when studying heatsink lag. Five-minute averages alone
   cannot locate a response delay to the second or prove causality.
5. Compare charge/export/mixed flows at comparable starting AC/DC and ambient
   temperatures. Test whether voltage and humidity improve held-out-day accuracy.
6. Report coverage and uncertainty. Do not automatically apply a cooling matrix
   from correlations; validate on later complete warming/cooling cycles first.

The first deliverable is a clean observation dataset and measured operating
coverage, not an automatically trained replacement controller.

## Deployment receipt — 13 September 2026

v0.6.0b8 (`d24a36a`, branch `overhaul`) was installed and Home Assistant restarted.
The collector began around 00:23 NZST. Its first saved window ended at 00:25 NZST,
with one successful write and zero write failures. The compressed file was copied
back over SMB, decoded and processed by the review command with CSV export.
This first window is partial and includes startup temperature unavailability;
exclude it from cooling comparisons. Garage readings recovered to 12.3 °C and
59% humidity, and the actual fan returned from startup failsafe to 10%.

The Power page includes a collection-status row and a collection toggle. Raw data
stays in HA's dedicated data directory; neither measurements nor credentials are
committed. Plan the first analysis around **20 September 2026**, subject to usable
coverage. No automatic review or reminder has been scheduled.
