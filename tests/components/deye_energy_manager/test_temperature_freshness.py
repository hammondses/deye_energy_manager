from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from custom_components.deye_energy_manager.temperature_freshness import temperature_reported_at


def test_unchanged_mqtt_temperature_is_fresh_but_silence_and_unrelated_messages_are_not():
    now = datetime.now(timezone.utc)
    state = SimpleNamespace(entity_id='sensor.ac', state='26.6', last_reported=now-timedelta(minutes=5))
    msg = SimpleNamespace(payload='26.6', timestamp=985, retain=False)
    info = {'discovery_data': {'discovery_payload': {'state_topic': 'ac'}},
            'subscriptions': {'ac': {'messages': [msg]}, 'availability': {'messages': [SimpleNamespace(payload='online', timestamp=1000)]}}}
    mqtt = SimpleNamespace(debug_info_entities={'sensor.ac': info})
    cache = {}
    stamp = temperature_reported_at(state, mqtt, now, 1000, cache)
    assert (now-stamp).total_seconds() == 15
    # Time passes without another report: the same receipt must age into failsafe.
    later = now+timedelta(seconds=70)
    assert (later-temperature_reported_at(state, mqtt, later, 1070, cache)).total_seconds() == 85
    for payload, retained in [('26.6', True), ('nan', False), ('unavailable', False), ('29', False)]:
        msg.payload, msg.retain = payload, retained
        assert temperature_reported_at(state, mqtt, now, 1000, cache) == state.last_reported
    assert temperature_reported_at(state, None, now, 1000, cache) == state.last_reported


def test_one_mqtt_receipt_has_one_identity_despite_clock_conversion_jitter():
    now = datetime.now(timezone.utc)
    state = SimpleNamespace(entity_id='sensor.ac', state='44.1', last_reported=now-timedelta(minutes=2))
    msg = SimpleNamespace(payload='44.1', timestamp=100, retain=False)
    mqtt = SimpleNamespace(debug_info_entities={'sensor.ac': {
        'discovery_data': {'discovery_payload': {'state_topic': 'ac'}},
        'subscriptions': {'ac': {'messages': [msg]}},
    }})
    cache = {}
    first = temperature_reported_at(state, mqtt, now, 100, cache)
    for elapsed in [5, 10, 15]:
        assert temperature_reported_at(state, mqtt, now+timedelta(seconds=elapsed, microseconds=3), 100+elapsed, cache) == first
    # A real new receipt with an unchanged value must still be recognised.
    msg.timestamp = 120
    assert temperature_reported_at(state, mqtt, now+timedelta(seconds=20), 120, cache) > first
    assert len(cache) == 1
