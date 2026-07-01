# Deye Energy Manager — Home Assistant Custom Integration Plan

## Summary

Build a Home Assistant custom integration called `deye_energy_manager`.

It should become the central policy brain for:

- Deye battery reserve planning
- Solcast forecast strategy
- cheap-grid battery charging
- EV charger grid-bypass/latch logic
- solar heat-pump / underfloor diversion
- battery-priority protection
- diagnostics and dashboard entities

Build the whole integration, but every control path must be behind explicit toggles. Default to advisory/read-only behaviour.

Current HA automations remain the prototype and fallback.

---

## Core architecture

The integration owns policy:

```text
forecast + battery + tariff + EV + heat state
→ active plan
→ permissions / required actions
→ optional actuator writes
```

Existing HA entities remain the actuator layer at first.

The integration should publish clear sensors/binary sensors showing what it would do and why. Once tested, switches can enable actual control.

---

## Feature toggles

Create switch entities and config options:

```text
switch.deye_energy_manager_enabled
switch.deye_energy_manager_advisory_enabled
switch.deye_energy_manager_deye_control_enabled
switch.deye_energy_manager_grid_charge_control_enabled
switch.deye_energy_manager_ev_control_enabled
switch.deye_energy_manager_heat_control_enabled
switch.deye_energy_manager_direct_climate_control_enabled
```

Defaults:

```text
enabled = on
advisory = on
all control toggles = off
direct climate control = off
```

Meaning:

- Advisory: publish decisions only.
- Deye control: write programme SOC floors / charge-source defaults.
- Grid charge control: allow grid charging on selected cheap slots.
- EV control: set Deye programme powers to 0/12000 for EV charging.
- Heat control: call heat add/shed scripts or directly control climates.
- Direct climate control: only control climate entities if explicitly enabled.

---

## Required input entities

Config flow should map these.

### Deye sensors

```text
sensor.deye_battery_soc
sensor.deye_battery_power
sensor.deye_grid_ct_power
sensor.deye_essential_power
sensor.deye_battery_rated_capacity
sensor.deye_battery_voltage
```

Current sign convention:

```text
battery_power > 0 = discharging
battery_power < 0 = charging
```

Derived:

```text
battery_charge_w = max(-battery_power, 0)
battery_discharge_w = max(battery_power, 0)
```

### Solcast / forecast sensors

```text
sensor.solcast_pv_forecast_forecast_today
sensor.solcast_pv_forecast_forecast_remaining_today
sensor.solcast_pv_forecast_forecast_tomorrow
sensor.solcast_pv_forecast_power_now
sensor.solcast_pv_forecast_power_in_30_minutes
sensor.solcast_pv_forecast_power_in_1_hour
```

### Deye programme capacity numbers

```text
number.deye_prog1_capacity
number.deye_prog2_capacity
number.deye_prog3_capacity
number.deye_prog4_capacity
number.deye_prog5_capacity
number.deye_prog6_capacity
```

### Deye programme power numbers

```text
number.deye_prog1_power
number.deye_prog2_power
number.deye_prog3_power
number.deye_prog4_power
number.deye_prog5_power
number.deye_prog6_power
```

### Deye programme charge-source selects

```text
select.deye_prog1_charge
select.deye_prog2_charge
select.deye_prog3_charge
select.deye_prog4_charge
select.deye_prog5_charge
select.deye_prog6_charge
```

Known select options:

```text
No Grid or Gen
Allow Grid
Allow Gen
Allow Grid & Gen
```

### Deye grid charge master

```text
switch.deye_grid_charge_enabled
```

### Optional Porsche / EV entities

```text
sensor.cayenne_e_hybrid_my24_state_of_charge
sensor.cayenne_e_hybrid_my24_charging_status
sensor.cayenne_e_hybrid_my24_charging_ends
sensor.cayenne_e_hybrid_my24_charging_power
```

Known issues:

```text
charging_status can be stale
charging_power can be stale/0
state_of_charge updates sporadically
charging_ends updates sporadically but is useful for ETA/hold-until
```

### Heat loads

Configure as a list. Each load should include:

```text
name
climate entity
ownership boolean
priority
estimated load W
hvac mode
target temp
type: heatpump / underfloor / other
```

Known current examples:

```text
climate.diningheatpump_mqtt_hvac
input_boolean.solar_owns_dining_heatpump

climate.master_bathroom_underfloor_heating
input_boolean.solar_owns_underfloor

climate.office_heatpump
input_boolean.solar_owns_office_heatpump

climate.bedroom_heatpump
input_boolean.solar_owns_bedroom_heatpump

climate.hallwayheatpump_mqtt_hvac
input_boolean.solar_owns_hallway_heatpump
```

Preferred priority:

```text
1. Dining/living heat pump
2. Underfloor small trim load
3. Office heat pump
4. Bedroom heat pump
5. Hallway heat pump
```

---

## Time windows and Deye slots

Local timezone:

```text
Pacific/Auckland
```

Tariff/strategy windows:

```text
21:00–07:00 cheap grid
07:00–13:00 expensive morning / solar ramp
13:00–17:00 pre-peak preserve
17:00–21:00 peak/heating battery-use window
```

Current Deye slots:

```text
Prog6: 21:00–02:00
Prog1: 02:00–04:00
Prog2: 04:00–06:55
Prog3: 06:55–13:00
Prog4: 13:00–17:00
Prog5: 17:00–21:00
```

Expose slot times/mapping as options later, but hard-code for MVP.

---

## Output entities

### Sensors

```text
sensor.deye_energy_manager_active_plan
sensor.deye_energy_manager_forecast_mode
sensor.deye_energy_manager_current_slot
sensor.deye_energy_manager_current_tariff_window
sensor.deye_energy_manager_today_forecast_kwh
sensor.deye_energy_manager_remaining_forecast_kwh
sensor.deye_energy_manager_tomorrow_forecast_kwh
sensor.deye_energy_manager_target_17_soc
sensor.deye_energy_manager_current_reserve_soc
sensor.deye_energy_manager_grid_charge_target_soc
sensor.deye_energy_manager_battery_charge_w
sensor.deye_energy_manager_battery_discharge_w
sensor.deye_energy_manager_pv_power_now_w
sensor.deye_energy_manager_expected_action
sensor.deye_energy_manager_last_decision_reason
sensor.deye_energy_manager_last_control_action
sensor.deye_energy_manager_ev_hold_until
```

### Binary sensors

```text
binary_sensor.deye_energy_manager_battery_priority_satisfied
binary_sensor.deye_energy_manager_heat_allowed
binary_sensor.deye_energy_manager_heat_should_shed
binary_sensor.deye_energy_manager_grid_charge_required
binary_sensor.deye_energy_manager_ev_grid_mode_required
binary_sensor.deye_energy_manager_pre_peak_preserve_required
binary_sensor.deye_energy_manager_safe_to_discharge
binary_sensor.deye_energy_manager_forecast_data_valid
binary_sensor.deye_energy_manager_control_blocked
```

### Selects

```text
select.deye_energy_manager_strategy
```

Options:

```text
off
conservative
normal
aggressive
manual
```

```text
select.deye_energy_manager_heat_mode
```

Options:

```text
off
advisory
auto_scripts
auto_direct
```

### Numbers

```text
number.deye_energy_manager_heat_add_min_charge_w
number.deye_energy_manager_heat_add_min_soc
number.deye_energy_manager_heat_shed_discharge_w
number.deye_energy_manager_ev_start_load_jump_w
number.deye_energy_manager_ev_stop_load_drop_w
number.deye_energy_manager_forecast_safety_buffer_kwh
number.deye_energy_manager_min_soc_floor
number.deye_energy_manager_max_grid_charge_target_soc
```

Defaults:

```text
heat_add_min_charge_w = 6000
heat_add_min_soc = 90
heat_shed_discharge_w = 500
ev_start_load_jump_w = 5000
ev_stop_load_drop_w = 6000
forecast_safety_buffer_kwh = 2
min_soc_floor = 12
max_grid_charge_target_soc = 80
```

### Buttons

```text
button.deye_energy_manager_apply_plan_now
button.deye_energy_manager_recalculate_now
button.deye_energy_manager_restore_deye_normal
button.deye_energy_manager_force_shed_one_heat_load
button.deye_energy_manager_force_add_one_heat_load
button.deye_energy_manager_clear_ev_latch
```

---

## Forecast strategy

Use tomorrow forecast:

```text
sensor.solcast_pv_forecast_forecast_tomorrow
```

Tier table:

| Forecast tomorrow | Mode | Overnight floor | Morning floor | Pre-peak floor | Peak floor | 17:00 target | Grid-charge target |
|---:|---|---:|---:|---:|---:|---:|---:|
| >= 32 kWh | excellent | 35% | 20% | 75% | 15% | 90% | 0% |
| 24–32 kWh | good | 40% | 25% | 80% | 15% | 90% | 0% |
| 16–24 kWh | medium | 50% | 35% | 80% | 20% | 85% | 0% |
| 10–16 kWh | poor | 65% | 50% | 85% | 25% | 85% | 65% |
| 6–10 kWh | dreadful | 75% | 60% | 85% | 30% | 85% | 75% |
| < 6 kWh | brutal | 80% | 65% | 85% | 30% | 85% | 80% |

Current reserve by time:

```text
21:00–06:55 => overnight_floor
06:55–13:00 => morning_floor
13:00–17:00 => pre_peak_floor
17:00–21:00 => peak_floor
```

Deye capacity writes, when enabled:

```text
Prog6 = overnight_floor
Prog1 = overnight_floor
Prog2 = overnight_floor
Prog3 = morning_floor
Prog4 = pre_peak_floor
Prog5 = peak_floor
```

---

## Heat logic

Forecast should not directly turn heat on.

Forecast sets the battery plan. Heat is allowed only when actual battery state proves battery priority is satisfied.

### Heat allowed

```python
heat_allowed = (
    manager_enabled
    and heat_available
    and time_between("08:00", "17:00")
    and cooldown_passed
    and (
        battery_charge_w >= heat_add_min_charge_w
        or battery_soc >= target_17_soc
    )
    and battery_discharge_w < 200
)
```

### Heat should shed

```python
heat_should_shed = (
    any_solar_owned_heat_load_on
    and (
        battery_discharge_w >= heat_shed_discharge_w
        or (
            battery_charge_w < heat_add_min_charge_w
            and battery_soc < target_17_soc
        )
        or pre_peak_preserve_required
    )
)
```

### Pre-peak preserve

```python
pre_peak_preserve_required = (
    time_between("13:00", "17:00")
    and battery_soc < target_17_soc
    and battery_charge_w < heat_add_min_charge_w
)
```

### Add one heat load

If `heat_allowed` and heat control enabled:

- add exactly one load per run
- choose first available load by configured priority
- set hvac mode and target temp
- set ownership boolean on
- record last action/time

### Shed one heat load

If `heat_should_shed` and heat control enabled:

- shed exactly one solar-owned load per run
- preserve manually enabled loads
- turn off ownership boolean
- record last action/time

Default action mode should call scripts, not direct climates, unless direct climate control is enabled.

Suggested scripts:

```text
script.deye_energy_manager_add_one_heat_load
script.deye_energy_manager_shed_one_heat_load
```

---

## EV grid mode logic

### Start EV grid mode

Start when cheap window and large load jump:

```python
ev_grid_mode_required = (
    time_between("21:00", "07:00")
    and essential_power_jump_w > ev_start_load_jump_w
)
```

Default jump:

```text
5000 W
```

Also recover on slot/startup if cheap window and essential load is already high:

```python
if cheap_window and essential_power_w > 6500:
    ev_grid_mode_required = True
```

### On EV mode start

If EV control enabled:

```text
Prog6 power = 0
Prog1 power = 0
Prog2 power = 0
Prog3 power = 0
EV latch = on
```

Set hold-until:

```python
if porsche_charging_ends is valid and future:
    ev_hold_until = porsche_charging_ends + 10 minutes
else:
    ev_hold_until = now + 3 hours
```

### Stop EV grid mode

Stop if any:

```text
07:00 failsafe
Porsche SOC >= 99%
instant essential/grid load drop > 6000 W
hold_until expired AND essential load < 2500 W
manual clear button
```

Important:

- sustained low-ish load alone is not enough because EV taper and heat pumps can mask it
- instant >6 kW drop remains valid as unplug/finished signal
- Porsche status is auxiliary only

### On EV mode stop

If EV control enabled:

```text
Prog6 power = 12000
Prog1 power = 12000
Prog2 power = 12000
Prog3 power = 12000
EV latch = off
```

---

## Cheap grid charging logic

Only allowed:

```text
03:00–07:00
```

Required when:

```python
grid_charge_required = (
    grid_charge_control_enabled
    and time_between("03:00", "07:00")
    and grid_charge_target_soc > 0
    and battery_soc < grid_charge_target_soc - 1
    and not ev_grid_mode_required
)
```

When enabled:

```text
switch.deye_grid_charge_enabled = on
select.deye_prog1_charge = Allow Grid
select.deye_prog2_charge = Allow Grid
number.deye_prog1_capacity = grid_charge_target_soc
number.deye_prog2_capacity = grid_charge_target_soc
number.deye_prog1_power = 12000
number.deye_prog2_power = 12000
```

When disabled:

```text
select.deye_prog1_charge = No Grid or Gen
select.deye_prog2_charge = No Grid or Gen
```

After 07:00:

```text
switch.deye_grid_charge_enabled = off
```

---

## Decision object

Create a pure Python dataclass:

```python
@dataclass
class EnergyManagerDecision:
    now: datetime
    forecast_mode: str
    active_slot: str
    tariff_window: str
    target_17_soc: float
    current_reserve_soc: float
    grid_charge_target_soc: float
    battery_soc: float
    battery_power_w: float
    battery_charge_w: float
    battery_discharge_w: float
    battery_priority_satisfied: bool
    heat_allowed: bool
    heat_should_shed: bool
    grid_charge_required: bool
    ev_grid_mode_required: bool
    pre_peak_preserve_required: bool
    control_blocked: bool
    reason: str
    proposed_actions: list[str]
```

Most sensors should expose this decision.

---

## Diagnostics / reasons

Every decision should include a readable reason.

Examples:

```text
heat_allowed=false: SOC 31.5 < target_17 90 and charge 363W < 6000W
heat_allowed=true: charge 6420W >= 6000W
grid_charge_required=true: forecast brutal, SOC 54 < target 80, EV mode off
ev_grid_mode_required=true: essential load jumped +6200W in cheap window
pre_peak_preserve_required=true: SOC 72 < target_17 90 and charge 1200W < 6000W
```

Expose:

```text
sensor.deye_energy_manager_last_decision_reason
```

Also log control writes at info/debug level.

---

## Coordinator

Use `DataUpdateCoordinator`.

Suggested interval:

```text
30 seconds
```

Also react to state changes for:

```text
battery SOC
battery power
essential power
grid power
forecast sensors
Porsche charging ends/SOC/status
feature toggles
heat ownership states
```

Startup grace before writes:

```text
60 seconds
```

---

## Safety / idempotency

Before writing any entity:

- feature toggle must be enabled
- entity must exist and be available
- value must actually need changing
- rate-limit repeated writes
- do not spam Deye with identical writes
- keep last-written values in memory
- write reasons to diagnostics

If optional entities are missing, degrade gracefully and stay advisory for that feature.

---

## Tests

Implement pure logic tests for `decision.py`.

### Forecast tier tests

```text
35 kWh -> excellent, target_17 90, grid target 0
27 kWh -> good
20 kWh -> medium
12 kWh -> poor, grid target 65
8 kWh -> dreadful, grid target 75
4 kWh -> brutal, grid target 80
```

### Time slot tests

```text
22:00 -> Prog6 / overnight
03:00 -> Prog1 / overnight
05:00 -> Prog2 / overnight
07:30 -> Prog3 / morning
14:00 -> Prog4 / pre-peak
18:00 -> Prog5 / peak
```

### Heat tests

```text
SOC 31, charge 300W -> heat_allowed false
SOC 31, charge 6500W -> heat_allowed true
SOC 91, charge 0W -> heat_allowed true
SOC 85, target_17 90, charge 2000W -> heat_allowed false
owned load on + discharge 600W -> heat_should_shed true
owned load on + SOC 31 + charge 300W -> heat_should_shed true
owned load on + SOC 91 -> heat_should_shed false
no owned loads -> heat_should_shed false
```

### Grid charge tests

```text
poor forecast, target 65, SOC 50, 04:00, EV false -> true
same but EV true -> false
same but 08:00 -> false
excellent forecast, target 0 -> false
```

### EV tests

```text
essential load jump +5200W during cheap window -> start
taper to 3200W should not stop
instant drop -6500W -> stop
SOC >= 99 -> stop
07:00 -> stop
hold expired + essential <2500 -> stop
```

---

## File structure

```text
custom_components/deye_energy_manager/
  __init__.py
  manifest.json
  const.py
  config_flow.py
  coordinator.py
  decision.py
  models.py
  sensor.py
  binary_sensor.py
  switch.py
  select.py
  number.py
  button.py
  services.yaml
  strings.json
  translations/en.json

tests/components/deye_energy_manager/
  test_decision.py
  test_config_flow.py
  test_sensor.py
```

---

## Manifest

```json
{
  "domain": "deye_energy_manager",
  "name": "Deye Energy Manager",
  "codeowners": [],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/<user>/<repo>",
  "iot_class": "local_push",
  "requirements": [],
  "version": "0.1.0"
}
```

---

## MVP phases

### Phase 1

Build the full integration skeleton, config flow, decision engine, entities, and tests.

All controls default off.

### Phase 2

Enable Deye capacity/slot writing behind `deye_control_enabled`.

### Phase 3

Enable cheap grid charge control behind `grid_charge_control_enabled`.

### Phase 4

Enable EV grid-bypass/latch behind `ev_control_enabled`.

### Phase 5

Enable heat control behind `heat_control_enabled`.

Use scripts first, then direct climate control only if explicitly enabled.

---

## Migration path

1. Leave current automations running.
2. Install integration in advisory mode.
3. Compare integration decisions to current HA behaviour.
4. Update existing automations to consume:
   ```text
   binary_sensor.deye_energy_manager_heat_allowed
   binary_sensor.deye_energy_manager_heat_should_shed
   binary_sensor.deye_energy_manager_grid_charge_required
   binary_sensor.deye_energy_manager_ev_grid_mode_required
   ```
5. Enable Deye control.
6. Enable grid charge control.
7. Enable EV control.
8. Enable heat control.
9. Disable old automations once integration behaviour is trusted.

---

## Codex instruction

Build this integration from the spec.

Priorities:

1. Correct decision engine with tests.
2. HA entities exposing decisions and reasons.
3. Config flow and options.
4. Feature toggles.
5. Safe actuator functions behind toggles.
6. Useful logs and diagnostics.

Do not assume optional Porsche or heat entities exist. Missing optional entities should not break setup.
