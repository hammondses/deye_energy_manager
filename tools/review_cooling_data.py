"""Read compressed cooling windows and report/export a rolling week. Stdlib only."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path


def review(directory, days=7, csv_path=None):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for path in sorted(Path(directory).glob('????-??-??.jsonl.gz')):
        with gzip.open(path, 'rt') as stream:
            for line in stream:
                row = json.loads(line)
                if datetime.fromisoformat(row['start']) >= cutoff:
                    # User confirmed all pre-metadata b8/b9 observations used this setup.
                    if 'hardware' not in row['context'] and row['context'].get('manager_version') in {'0.6.0b8', '0.6.0b9'}:
                        row['context']['hardware'] = {
                            'cooling_airflow_direction': 'Stock direction',
                            'cooling_fan_arrangement': 'Intake + exhaust',
                            'cooling_intake_fan_count': 3,
                            'cooling_exhaust_fan_count': 4,
                        }
                        row['context']['hardware_source'] = 'user-confirmed historical setup'
                    rows.append(row)
    print(f'# Cooling observations · last {days} days\n')
    print(f'{len(rows)} windows ({len(rows)/12:.1f} hours represented).')
    print('Counts include partial windows. These are observations, not recommended fan settings.\n')
    versions = Counter(r['context'].get('manager_version', 'unknown') for r in rows)
    print('Versions:', dict(versions))
    flags = Counter(k for r in rows for k, seconds in r['flag_seconds'].items() if seconds)
    print('Windows with flags:', dict(flags))
    print('Windows with tuning changes:', sum(r['context_changed'] for r in rows))
    required = ('pv_w', 'battery_w', 'grid_w', 'house_w', 'ac_c', 'dc_c', 'garage_c', 'fan_pct')
    complete = [r for r in rows if all(r['fields'].get(k, {}).get('coverage', 0) >= .9 for k in required)]
    print(f'Windows with ≥90% coverage of core fields: {len(complete)} / {len(rows)}')
    print('\n| Field | Observed minimum | Observed maximum |\n|---|---:|---:|')
    for key in (*required, 'grid_v', 'import_grid_v', 'export_grid_v', 'humidity_pct', 'balance_w'):
        fields = [r['fields'][key] for r in rows if key in r['fields']]
        if fields:
            print(f'| {key} | {min(f["min"] for f in fields):.2f} | {max(f["max"] for f in fields):.2f} |')
    if csv_path and rows:
        flat = []
        for row in rows:
            out = {k:row[k] for k in ('start', 'end', 'samples', 'fan_changes', 'context_changed')}
            out['manager_version'] = row['context'].get('manager_version')
            out.update(row['context'].get('hardware', {}))
            out['hardware_source'] = row['context'].get('hardware_source', 'recorded' if 'hardware' in row['context'] else 'unknown')
            out['context_json'] = json.dumps(row['context'], sort_keys=True)
            for key, metrics in row['fields'].items():
                out.update({f'{key}_{metric}':value for metric, value in metrics.items()})
            out.update({f'flag_{k}_seconds':v for k,v in row['flag_seconds'].items()})
            out.update({f'share_{k}_pct':v for k,v in (row['destination_share_pct'] or {}).items()})
            flat.append(out)
        with open(csv_path, 'w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted({k for r in flat for k in r}))
            writer.writeheader()
            writer.writerows(flat)
        print(f'\nCSV: {csv_path}')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--csv')
    args = parser.parse_args()
    review(args.directory, args.days, args.csv)
