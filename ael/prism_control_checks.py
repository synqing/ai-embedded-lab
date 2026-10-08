"""Pure readback checks for Titan ControlOwner's 160-byte state contract.

No port, programming, playback or persistence operation is performed here.
Float controls compare their encoded IEEE-754 binary32 words, not rounded text.
"""
import math
import struct

FLAG_FIELDS = (10, 11, 12, 13, 14, 16, 17)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _uint(value, name):
    _require(type(value) is int and 0 <= value <= 0xFFFFFFFF, 'Invalid ' + name)
    return value


def decode_state(body, expected_schema):
    """Decode and validate a successful native state response, all 18 fields."""
    _require(isinstance(body, (bytes, bytearray)) and len(body) == 160, 'Wrong control state length')
    _require(isinstance(expected_schema, str) and len(expected_schema) == 64 and
             all(c in '0123456789abcdef' for c in expected_schema), 'Invalid expected control schema')
    words = struct.unpack('<40I', body)
    _require(words[:3] == (0x454D5354, 1, 1), 'Wrong control magic/version')
    _require(body[108:140].hex() == expected_schema, 'Wrong control schema')
    _require(words[3] > 0 and words[5] > 0, 'Invalid control boot/request identity')
    _require(words[23] == 0, 'Control rejection status ' + str(words[23]))
    _require(all(v in (0, 1) for v in words[24:27]), 'Invalid control response flags')
    _require(words[16] & ~0x7F == 0, 'Unknown control setting flag')
    _require(words[14] == words[8], 'Duplicated float control differs')
    _require(not any(words[36:40]), 'Nonzero reserved control words')
    settings = list(words[6:14]) + [words[15]] + [0] * 9
    fields = {str(i + 1): struct.unpack('<f', struct.pack('<I', settings[i]))[0] for i in range(8)}
    _require(all(math.isfinite(v) and 0 <= v <= 1 for v in fields.values()), 'Invalid float control')
    for bit, field in enumerate(FLAG_FIELDS):
        settings[field - 1] = (words[16] >> bit) & 1
    settings[14], settings[17] = words[17], words[35]
    _require(settings[8] <= 6, 'Invalid control mode')
    _require(settings[14] <= 255, 'Invalid control brightness')
    _require(settings[17] <= 44, 'Invalid control palette')
    expected_available = 0xFFFF & ~(0 if settings[8] == 0 else 1 << 5) & ~(0 if fields['5'] > 0 else 1 << 13)
    _require(words[18] == expected_available, 'Control applicability mask differs from settings')
    fields.update({str(i + 1): settings[i] for i in range(8, 18)})
    return dict(boot=words[3], revision=words[4], request=words[5],
                mode=settings[8], brightness=settings[14], palette=settings[17],
                flags=words[16], available=words[18], accepted=words[19],
                rendered=words[20], emitted=words[21], frame=words[22],
                status=words[23], deduplicated=words[24], changed=words[25],
                mode_transition=words[26], schema_sha256=expected_schema,
                fields=fields, settings_words=settings)


def _encoded_fields(fields):
    _require(isinstance(fields, dict) and 1 <= len(fields) <= 18, 'Invalid requested field set')
    encoded = {}
    for key, value in fields.items():
        _require(type(key) in (int, str), 'Invalid requested field identifier')
        try:
            field = int(key)
        except (ValueError, TypeError):
            raise ValueError('Invalid requested field identifier') from None
        _require(1 <= field <= 18 and field not in encoded, 'Duplicate/unknown requested field')
        if field <= 8:
            _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1, 'Invalid requested float')
            word = struct.unpack('<I', struct.pack('<f', value))[0]
        else:
            if field in FLAG_FIELDS and type(value) is bool:
                value = int(value)
            word = _uint(value, 'requested integer')
            limit = 6 if field == 9 else 255 if field == 15 else 44 if field == 18 else 1
            _require(word <= limit, 'Requested integer outside control range')
        encoded[field] = word
    return encoded


def _identity(value, boot, request, schema):
    _require(value['boot'] == _uint(boot, 'expected boot') and boot > 0, 'Control boot changed')
    _require(value['request'] == _uint(request, 'expected request') and request > 0, 'Control request changed')
    _require(value['schema_sha256'] == schema, 'Control schema changed')
    _require(value['status'] == 0, 'Control status is not successful')


def verify_applied(initial, applied, fields, *, boot, request):
    """Require a new PATCH to apply exactly the requested complete state delta."""
    _identity(applied, boot, request, initial['schema_sha256'])
    _require(initial['boot'] == boot and initial['status'] == 0, 'Invalid initial control state')
    expected = list(initial['settings_words'])
    _require(len(expected) == 18, 'Incomplete initial control settings')
    for field, word in _encoded_fields(fields).items():
        expected[field - 1] = word
    _require(applied['settings_words'] == expected, 'Applied control settings differ from requested state')
    changed = expected != initial['settings_words']
    revision = (initial['revision'] + int(changed)) & 0xFFFFFFFF
    _require(applied['revision'] == revision, 'Applied control revision did not match change')
    _require(applied['accepted'] == (request if changed else initial['accepted']), 'Accepted control request mismatch')
    _require(applied['deduplicated'] == 0, 'Unexpected cached control response')
    _require(applied['changed'] == int(changed), 'Control changed flag mismatch')
    _require(applied['mode_transition'] == int(expected[8] != initial['settings_words'][8]), 'Control mode transition mismatch')
    return applied


def verify_readback(applied, observed, *, boot, request):
    """Require fresh GET to retain accepted revision and all settings, no save."""
    _identity(observed, boot, request, applied['schema_sha256'])
    _require(applied['boot'] == boot and applied['status'] == 0, 'Invalid applied control state')
    _require(observed['revision'] == applied['revision'] and observed['accepted'] == applied['accepted'], 'Readback lost accepted control revision')
    _require(observed['settings_words'] == applied['settings_words'], 'Readback control settings changed')
    _require(observed['deduplicated'] == observed['changed'] == observed['mode_transition'] == 0, 'GET returned PATCH response flags')
    return observed
