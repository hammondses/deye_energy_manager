# Battery automation damping — 4 October 2026

Deployed to the existing battery automation at approximately 10:45 NZDT through
the HA configuration API. Runtime manager remains 0.6.0b20; the 0.6.0b21 source
release records this automation-only change and needs no manager restart.

The morning history showed 468 current-limit transitions between 09:00 and
10:24, cycling between 1 and 8 A. Probing was eligible near the scheduled AC
target even below the physical export/AC ceiling. The feedback then undid it.

The revised shared-plan path has a 200 W / 3 A correction deadband, 10-second
increase settling, 45-second reduction settling, and a 120-second 1 A probe
interval limited to proximity to the physical AC/export ceiling. Reduced live
BMS/DC ceilings bypass damping. Timing uses current-limit last_changed, not
last_triggered, so frequent automation triggers do not reset or evade it.

The planner, EV automation, headroom strategy, existing active-branch gates,
and legacy fallback are unchanged. No background charge was introduced.

All 365 regression tests passed, including noise suppression, fast capture,
slow release, probe eligibility/cooldown, immediate ceiling reduction and
legacy behavior. New expressions also rendered in HA before deployment.

Rollback: replace only this automation's configuration through the HA API with
`live-config-backups/2026-10-04-battery-before-damping.json`'s `config` object.
The matching deployed configuration is in
`live-config-backups/2026-10-04-battery-after-damping.json`. Preserve its enabled
state. Do not restore the whole HA instance or change manager ownership.

## Immediate live verification

HA readback exactly matched the deployed config (hash `356b8da72a070967`),
and configuration validation passed. At 10:46:10 the natural control trace
finished normally with the manager path active, an AC error of -29 W and
a 3 A gate; both correction and probe conditions correctly rejected a write.
From 10:45:16 to 10:47:55, recorder history contained no current-limit changes.
The gate remained 3 A, battery charging was about 157 W, PV 10.92 kW and
export 9.53 kW. This confirms suppression below the physical ceiling over
the initial observation window, not yet a sustained clipping response.
