import gzip
import json

from custom_components.deye_energy_manager.cooling_data import CoolingWindows, append_window


def test_energy_split_directional_voltage_and_time_weighted_windows():
    collector = CoolingWindows()
    context = {'manager_version': 'test'}
    rows = []
    for t in range(0, 301, 15):
        rows += collector.add(t, dict(pv_w=12000, battery_w=-4800, grid_w=-6000,
            essential_w=1200, nonessential_w=0, grid_v=245, fan_pct=40,
            ac_c=45+t/300, garage_c=22), {}, context)
    assert len(rows) == 1
    row = rows[0]
    assert row['fields']['pv_w']['wh'] == 1000
    assert row['fields']['ac_c']['coverage'] == 1
    assert row['destination_share_pct'] == dict(battery_charge_w=40, house_w=10, grid_export_w=50)
    assert row['fields']['export_grid_v']['mean'] == 245
    assert 'import_grid_v' not in row['fields']
    assert row['fields']['balance_w']['mean'] == 0


def test_reversals_do_not_cancel_and_gaps_are_not_carried_forward():
    collector = CoolingWindows()
    rows = []
    for t in range(0, 301, 15):
        importing = t < 150
        rows += collector.add(t, {'grid_w':1000 if importing else -1000,
            'battery_w':-500 if importing else 500, 'grid_v':220 if importing else 245}, {}, {})
    row = rows[0]['fields']
    assert row['grid_w']['mean'] == 0
    assert row['grid_import_w']['wh'] == row['grid_export_w']['wh'] == 41.66667
    assert row['battery_charge_w']['wh'] == row['battery_discharge_w']['wh'] == 20.83333
    assert row['import_grid_v']['mean'] == 220
    assert row['export_grid_v']['mean'] == 245
    collector = CoolingWindows()
    collector.add(0, {'pv_w':1000}, {}, {})
    row = collector.add(3600, {'pv_w':None}, {}, {})[0]
    assert row['fields']['pv_w']['seconds'] == 30
    assert row['fields']['pv_w']['coverage'] == .1


def test_partial_windows_missing_data_settings_changes_and_compressed_storage(tmp_path):
    collector = CoolingWindows()
    rows = []
    for t in range(150, 301, 15):
        rows += collector.add(t, {'fan_pct':20 if t<225 else 30, 'pv_w':float('nan')},
                              {'recovery':t<225}, {'setting':t<225})
    row = rows[0]
    assert row['fields']['fan_pct']['coverage'] == .5
    assert row['fan_changes'] == 1
    assert row['flag_seconds']['recovery'] == 75
    assert row['context_changed']
    assert 'pv_w' not in row['fields']
    assert row['destination_share_pct'] is None
    append_window(tmp_path, row)
    append_window(tmp_path, row)
    with gzip.open(next(tmp_path.glob('*.gz')), 'rt') as f:
        assert [json.loads(line) for line in f] == [row, row]
    from tools.review_cooling_data import review
    export = tmp_path / 'review.csv'
    assert len(review(tmp_path, days=50000, csv_path=export)) == 2
    assert 'fan_pct_mean' in export.read_text()


def test_retention_removes_only_old_collection_files(tmp_path):
    (tmp_path / '2020-01-01.jsonl.gz').write_bytes(b'old')
    (tmp_path / 'notes.txt').write_text('keep')
    append_window(tmp_path, {'start': '2026-09-13T00:00:00+00:00'})
    assert not (tmp_path / '2020-01-01.jsonl.gz').exists()
    assert (tmp_path / 'notes.txt').exists()


def test_hardware_labels_mark_mixed_windows_and_preserve_counts():
    from custom_components.deye_energy_manager.cooling_data import cooling_hardware
    stock = cooling_hardware({})
    assert stock['cooling_intake_fan_count'] == 3
    assert stock['cooling_exhaust_fan_count'] == 4
    reverse = cooling_hardware({'cooling_airflow_direction': 'Reverse direction',
        'cooling_fan_arrangement': 'Intake only', 'cooling_intake_fan_count': 4,
        'cooling_exhaust_fan_count': 0})
    collector = CoolingWindows()
    rows = []
    for t in range(0, 601, 15):
        rows += collector.add(t, {'fan_pct': 40}, {}, {'hardware': stock if t < 150 else reverse})
    assert rows[0]['context_changed'] is True
    assert rows[1]['context_changed'] is False
    assert rows[1]['context']['hardware'] == reverse
