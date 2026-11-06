"""Trusted offline decoder example. Input: recorded events; no device handle."""
def decode(payload):
    pending = {}
    samples = []
    for event in payload.get('events', []):
        if event.get('direction', 'RX') != 'RX':
            continue
        session = event.get('session_id', event.get('port', 'legacy'))
        text = pending.get(session, b'') + bytes.fromhex(event.get('data', ''))
        while b'\n' in text:
            line, _, text = text.partition(b'\n')
            try:
                name, value = line.decode('ascii').strip().split('=', 1)
                samples.append({'t': event['elapsed_ms'], 'channel': name, 'value': float(value),
                                'source': event.get('seq'), 'session': session})
            except (ValueError, KeyError, UnicodeError):
                continue
        pending[session] = text[-4096:]
    return {'samples': samples, 'annotations': [{'message': 'Offline ASCII key=value analysis'}]}
