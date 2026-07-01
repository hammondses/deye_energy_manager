"""Constants for Deye Energy Manager."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "deye_energy_manager"
NAME = "Deye Energy Manager"

PLATFORMS = ["sensor", "binary_sensor", "switch", "select", "number", "button"]

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
STARTUP_GRACE = timedelta(seconds=60)
WRITE_RATE_LIMIT = timedelta(seconds=60)

CONF_ENTITY_MAP = "entity_map"
CONF_HEAT_LOADS = "heat_loads"

DEFAULT_ENTITY_MAP = {
    "battery_soc": "sensor.deye_battery_soc",
    "battery_power": "sensor.deye_battery_power",
    "grid_ct_power": "sensor.deye_grid_ct_power",
    "essential_power": "sensor.deye_essential_power",
    "battery_rated_capacity": "sensor.deye_battery_rated_capacity",
    "battery_voltage": "sensor.deye_battery_voltage",
    "forecast_today": "sensor.solcast_pv_forecast_forecast_today",
    "forecast_remaining_today": "sensor.solcast_pv_forecast_forecast_remaining_today",
    "forecast_tomorrow": "sensor.solcast_pv_forecast_forecast_tomorrow",
    "pv_power_now": "sensor.solcast_pv_forecast_power_now",
    "pv_power_in_30_minutes": "sensor.solcast_pv_forecast_power_in_30_minutes",
    "pv_power_in_1_hour": "sensor.solcast_pv_forecast_power_in_1_hour",
    "grid_charge_switch": "switch.deye_grid_charge_enabled",
    "porsche_soc": "sensor.cayenne_e_hybrid_my24_state_of_charge",
    "porsche_charging_status": "sensor.cayenne_e_hybrid_my24_charging_status",
    "porsche_charging_ends": "sensor.cayenne_e_hybrid_my24_charging_ends",
    "porsche_charging_power": "sensor.cayenne_e_hybrid_my24_charging_power",
}

DEFAULT_HEAT_LOADS = [
    {
        "name": "Dining/living heat pump",
        "climate_entity": "climate.diningheatpump_mqtt_hvac",
        "ownership_entity": "input_boolean.solar_owns_dining_heatpump",
        "priority": 1,
        "estimated_load_w": 2500,
        "hvac_mode": "heat",
        "target_temp": 23,
        "type": "heatpump",
    },
    {
        "name": "Bathroom underfloor",
        "climate_entity": "climate.master_bathroom_underfloor_heating",
        "ownership_entity": "input_boolean.solar_owns_underfloor",
        "priority": 2,
        "estimated_load_w": 800,
        "hvac_mode": "heat",
        "target_temp": 24,
        "type": "underfloor",
    },
    {
        "name": "Office heat pump",
        "climate_entity": "climate.office_heatpump",
        "ownership_entity": "input_boolean.solar_owns_office_heatpump",
        "priority": 3,
        "estimated_load_w": 1800,
        "hvac_mode": "heat",
        "target_temp": 22,
        "type": "heatpump",
    },
    {
        "name": "Bedroom heat pump",
        "climate_entity": "climate.bedroom_heatpump",
        "ownership_entity": "input_boolean.solar_owns_bedroom_heatpump",
        "priority": 4,
        "estimated_load_w": 1800,
        "hvac_mode": "heat",
        "target_temp": 21,
        "type": "heatpump",
    },
    {
        "name": "Hallway heat pump",
        "climate_entity": "climate.hallwayheatpump_mqtt_hvac",
        "ownership_entity": "input_boolean.solar_owns_hallway_heatpump",
        "priority": 5,
        "estimated_load_w": 1800,
        "hvac_mode": "heat",
        "target_temp": 21,
        "type": "heatpump",
    },
]

PROG_CAPACITY_ENTITIES = [
    "number.deye_prog1_capacity",
    "number.deye_prog2_capacity",
    "number.deye_prog3_capacity",
    "number.deye_prog4_capacity",
    "number.deye_prog5_capacity",
    "number.deye_prog6_capacity",
]

PROG_POWER_ENTITIES = [
    "number.deye_prog1_power",
    "number.deye_prog2_power",
    "number.deye_prog3_power",
    "number.deye_prog4_power",
    "number.deye_prog5_power",
    "number.deye_prog6_power",
]

PROG_CHARGE_SELECT_ENTITIES = [
    "select.deye_prog1_charge",
    "select.deye_prog2_charge",
    "select.deye_prog3_charge",
    "select.deye_prog4_charge",
    "select.deye_prog5_charge",
    "select.deye_prog6_charge",
]

FEATURE_DEFAULTS = {
    "enabled": True,
    "advisory_enabled": True,
    "deye_control_enabled": False,
    "grid_charge_control_enabled": False,
    "ev_control_enabled": False,
    "heat_control_enabled": False,
    "direct_climate_control_enabled": False,
    "pv_load_test_control_enabled": False,
    "export_limited_mode_enabled": False,
}

NUMBER_DEFAULTS = {
    "heat_add_min_charge_w": 6000.0,
    "heat_add_min_soc": 90.0,
    "heat_shed_discharge_w": 500.0,
    "ev_start_load_jump_w": 5000.0,
    "ev_stop_load_drop_w": 6000.0,
    "forecast_safety_buffer_kwh": 2.0,
    "min_soc_floor": 12.0,
    "max_grid_charge_target_soc": 80.0,
    "pv_load_test_min_soc": 70.0,
    "pv_load_test_min_expected_power_w": 4000.0,
    "pv_load_test_max_battery_charge_w": 2500.0,
    "pv_load_test_min_remaining_forecast_kwh": 8.0,
}

STRATEGY_OPTIONS = ["off", "conservative", "normal", "aggressive", "manual"]
DEFAULT_STRATEGY = "normal"

HEAT_MODE_OPTIONS = ["off", "advisory", "auto_scripts", "auto_direct"]
DEFAULT_HEAT_MODE = "advisory"

CHARGE_OPTION_NO_GRID = "No Grid or Gen"
CHARGE_OPTION_ALLOW_GRID = "Allow Grid"
