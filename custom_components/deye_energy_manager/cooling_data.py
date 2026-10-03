"""Five-minute observational cooling windows; no actuator writes or dependencies."""

from datetime import datetime, timezone, timedelta
import gzip
import json
from math import isfinite
from pathlib import Path

HARDWARE_DEFAULTS = {
    "cooling_airflow_direction": "Stock direction",
    "cooling_fan_arrangement": "Intake + exhaust",
    "cooling_intake_fan_count": 3,
    "cooling_exhaust_fan_count": 4,
}


def cooling_hardware(options):
    """User-declared physical setup, independent of controller tuning."""
    return {key: options.get(key, default) for key, default in HARDWARE_DEFAULTS.items()}


SAMPLE_SECONDS = 15
WINDOW_SECONDS = 300


def flow_values(values):
    """Keep signed channels and directional energy; never infer PV provenance."""
    result = {k: float(v) for k, v in values.items() if v is not None and isfinite(v)}
    for channel, positive, negative in [
        ('battery_w', 'battery_discharge_w', 'battery_charge_w'),
        ('grid_w', 'grid_import_w', 'grid_export_w'),
    ]:
        if channel in result:
            result[positive] = max(result[channel], 0)
            result[negative] = max(-result[channel], 0)
    if all(k in result for k in ('essential_w', 'nonessential_w')):
        result['house_w'] = result['essential_w'] + result['nonessential_w']
    needed = ('pv_w', 'battery_w', 'grid_w', 'house_w')
    if all(k in result for k in needed):
        result['input_w'] = max(result['pv_w'], 0) + result['battery_discharge_w'] + result['grid_import_w']
        result['output_w'] = result['house_w'] + result['battery_charge_w'] + result['grid_export_w']
        result['balance_w'] = result['input_w'] - result['output_w']
        for key in ('battery_charge_w', 'house_w', 'grid_export_w'):
            result['split_' + key] = result[key]
    if 'grid_w' in result:
        direction = 'import' if result['grid_w'] > 50 else 'export' if result['grid_w'] < -50 else 'idle'
        for field in ('grid_v', 'grid_a'):
            if field in result:
                result[f'{direction}_{field}'] = result[field]
    for channel in ('ac_c', 'dc_c'):
        if channel in result and 'garage_c' in result:
            result[f'{channel}_above_ambient'] = result[channel] - result['garage_c']
    return result


class CoolingWindows:
    """Time-weighted held samples; gaps beyond 30 seconds are missing, not zero."""

    def __init__(self):
        self.previous = None
        self.start = None
        self.stats = {}
        self.flags = {}
        self.context = None
        self.context_changed = False
        self.samples = 0
        self.fan_changes = 0
        self.last_fan = None

    def _finish(self):
        fields = {}
        for key, (total, seconds, low, high, first, last) in self.stats.items():
            fields[key] = dict(mean=round(total / seconds, 5), min=low, max=high,
                               first=first, last=last, delta=round(last-first, 5),
                               seconds=round(seconds, 3), coverage=round(seconds / WINDOW_SECONDS, 4))
            if key.endswith('_w'):
                fields[key]['wh'] = round(total / 3600, 5)
        # Only compare destination shares over equally covered observations.
        destinations = ['split_battery_charge_w', 'split_house_w', 'split_grid_export_w']
        shares = None
        if all(k in fields for k in destinations):
            coverage = [fields[k]['seconds'] for k in destinations]
            total = sum(fields[k]['wh'] for k in destinations)
            if max(coverage) == min(coverage) and total > 0:
                shares = {k.removeprefix('split_'): round(fields[k]['wh'] / total * 100, 3) for k in destinations}
        row = dict(schema=1, start=datetime.fromtimestamp(self.start, timezone.utc).isoformat(),
                   end=datetime.fromtimestamp(self.start+WINDOW_SECONDS, timezone.utc).isoformat(),
                   samples=self.samples, fields=fields, flag_seconds=self.flags,
                   fan_changes=self.fan_changes, context=self.context,
                   context_changed=self.context_changed, destination_share_pct=shares)
        self.stats, self.flags = {}, {}
        self.samples = self.fan_changes = 0
        self.context_changed = False
        self.last_fan = None
        self.context = None
        return row

    def add(self, timestamp, values, flags, context):
        rows = []
        current = flow_values(values)
        if self.previous and timestamp <= self.previous[0]:
            return rows
        if self.previous:
            t, previous, previous_flags, previous_context = self.previous
            end = min(timestamp, t + SAMPLE_SECONDS * 2)
            while t < end:
                bucket = int(t // WINDOW_SECONDS) * WINDOW_SECONDS
                if self.start is not None and bucket != self.start:
                    rows.append(self._finish())
                self.start = bucket
                self.context_changed |= self.context is not None and self.context != previous_context
                self.context = previous_context
                seconds = min(end, bucket + WINDOW_SECONDS) - t
                for key, value in previous.items():
                    stat = self.stats.setdefault(key, [0, 0, value, value, value, value])
                    stat[0] += value * seconds
                    stat[1] += seconds
                    stat[2], stat[3], stat[5] = min(stat[2], value), max(stat[3], value), value
                for key, value in previous_flags.items():
                    if value:
                        self.flags[key] = self.flags.get(key, 0) + seconds
                fan = previous.get('fan_pct')
                if fan is not None:
                    self.fan_changes += self.last_fan is not None and fan != self.last_fan
                    self.last_fan = fan
                self.samples += 1
                t += seconds
        bucket = int(timestamp // WINDOW_SECONDS) * WINDOW_SECONDS
        if self.start is not None and bucket != self.start:
            rows.append(self._finish())
            self.start = bucket
        self.previous = (timestamp, current, flags, context)
        return rows


def append_window(directory, row):
    """One compressed JSON row per window; retain only our last 90 days."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    day = row['start'][:10]
    with gzip.open(directory / f'{day}.jsonl.gz', 'at', encoding='utf-8') as stream:
        stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
    cutoff = (datetime.fromisoformat(row['start']) - timedelta(days=90)).date().isoformat()
    for path in directory.glob('????-??-??.jsonl.gz'):
        if path.name[:10] < cutoff:
            path.unlink()
