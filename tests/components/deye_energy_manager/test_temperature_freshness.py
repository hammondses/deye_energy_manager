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
    stamp = temperature_reported_at(state, mqtt, now, 1000)
    assert (now-stamp).total_seconds() == 15
    # Time passes without another report: the same receipt must age into failsafe.
    later = now+timedelta(seconds=70)
    assert (later-temperature_reported_at(state, mqtt, later, 1070)).total_seconds() == 85
    for payload, retained in [('26.6', True), ('nan', False), ('unavailable', False), ('29', False)]:
        msg.payload, msg.retain = payload, retained
        assert temperature_reported_at(state, mqtt, now, 1000) == state.last_reported
    assert temperature_reported_at(state, None, now, 1000) == state.last_reported
