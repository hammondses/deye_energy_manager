"""Use actual MQTT receipt times when HA suppresses unchanged sensor writes."""
from datetime import timedelta
from math import isfinite


def temperature_reported_at(state, mqtt_data, now, monotonic_now, receipt_cache):
    """Accept only fresh, non-retained numeric reports on this sensor's state topic.

    HA's MQTT receive cache is bounded and already maintained by the integration.
    Fall back to normal state timestamps if its layout changes or isn't present;
    never extend freshness using availability messages or another sensor's traffic.
    """
    reported = state.last_reported
    try:
        info = mqtt_data.debug_info_entities[state.entity_id]
        topic = info['discovery_data']['discovery_payload']['state_topic']
        messages = info['subscriptions'][topic]['messages']
        message = messages[-1]
        value = float(message.payload)
        age = monotonic_now - message.timestamp
        if not message.retain and isfinite(value) and value == float(state.state) and age >= 0:
            # Convert each monotonic receipt once. Reconstructing UTC on every
            # read introduces clock jitter that looks like a new temperature sample.
            token = (topic, message.timestamp, message.payload)
            cached = receipt_cache.get(state.entity_id)
            if cached is None or cached[0] != token:
                cached = (token, now - timedelta(seconds=age))
                receipt_cache[state.entity_id] = cached
            reported = max(reported, cached[1])
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        pass
    return reported
