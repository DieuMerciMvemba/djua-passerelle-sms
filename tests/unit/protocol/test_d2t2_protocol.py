import base64
import unittest

from djua_sms_gateway.protocol.d2 import (
    D2AuthStatus,
    D2ProtocolError,
    parse_d2,
)
from djua_sms_gateway.protocol.d2t2 import (
    D2T2_LAYOUT,
    D2T2_PAYLOAD_BYTES,
    D2T2_PAYLOAD_CHARS,
    normalize_d2t2_to_backend,
    parse_d2t2,
    verify_d2t2_security,
)
from djua_sms_gateway.protocol.dispatch import detect_protocol


KEY = bytes.fromhex(
    "000102030405060708090A0B0C0D0E0F"
    "101112131415161718191A1B1C1D1E1F"
)

D2T2_TYPICAL = (
    "D2T2,DJUA-KIN-000001,"
    "AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAAR"
    "gj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_A,"
    "rHcRllcP4gs"
)

D2T2_DEV_EMPTY = (
    "D2T2,DJUA-KIN-000001,"
    "AAAACgAAAAAAAAAAAAUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAA,-"
)

D2T_LEGACY = (
    "D2T,DJUA-KIN-000001,9IX,TM14E0,21I3V9,1E0,"
    "-99Q6,WU9O,9KG,DW,1Q,E1K,Y6,68,V4,1RX,3H,1VX,27W,9FL,3J,"
    "e0kwQvzx35g"
)


def rewrite_d2t2_fields(raw_message, **updates):
    protocol, device_id, payload, _auth = raw_message.split(",")
    packed = int.from_bytes(
        base64.urlsafe_b64decode(payload + "=="),
        "big",
    )
    total_bits = D2T2_PAYLOAD_BYTES * 8
    bit_offset = 0
    for name, width, signed in D2T2_LAYOUT:
        if name in updates:
            value = updates[name]
            if signed and value < 0:
                value += 1 << width
            shift = total_bits - bit_offset - width
            mask = ((1 << width) - 1) << shift
            packed = (packed & ~mask) | (value << shift)
        bit_offset += width
    encoded = packed.to_bytes(D2T2_PAYLOAD_BYTES, "big")
    updated_payload = base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
    return f"{protocol},{device_id},{updated_payload},-"


class D2T2ProtocolTests(unittest.TestCase):
    def test_dispatch_adds_d2t2_without_removing_existing_protocols(self):
        self.assertEqual(detect_protocol("D1,x"), "D1")
        self.assertEqual(detect_protocol("D2T,x"), "D2T")
        self.assertEqual(detect_protocol("D2T2,x"), "D2T2")
        self.assertEqual(detect_protocol("D2E,x"), "D2E")

        legacy = parse_d2(D2T_LEGACY)
        self.assertEqual(legacy.protocol_version, "D2T")
        self.assertEqual(legacy.sequence, 12345)

    def test_typical_message_decodes_dc_load_and_existing_measurements(self):
        message = parse_d2t2(D2T2_TYPICAL)
        self.assertEqual(len(message.payload), D2T2_PAYLOAD_CHARS)
        self.assertEqual(D2T2_PAYLOAD_BYTES, 60)
        self.assertEqual(message.sequence, 12345)
        self.assertEqual(message.battery_voltage, 12.4)
        self.assertEqual(message.solar_energy_interval_wh, 11.2)
        self.assertEqual(message.ac_active_power, 244.5)
        self.assertEqual(message.dc_load_voltage, 12.35)
        self.assertEqual(message.dc_load_current, 3.2)
        self.assertEqual(message.dc_load_power, 39.5)
        self.assertEqual(message.dc_load_energy_interval_wh, 19.76)
        self.assertIsNone(message.dc_load_measured_count)
        self.assertTrue(message.dc_load_valid)
        self.assertTrue(message.dc_load_energy_complete)

    def test_backend_mapping_keeps_existing_groups_and_adds_dc_load(self):
        message = parse_d2t2(D2T2_TYPICAL)
        status = verify_d2t2_security(
            message,
            mode="production",
            key=KEY,
            sender="+243810000001",
            allowed_senders=["+243810000001"],
        )
        payload = normalize_d2t2_to_backend(
            message,
            gateway_received_at="2026-09-27T15:30:05.123000+00:00",
            auth_status=status,
        )
        self.assertEqual(payload["protocol"], "D2T2")
        self.assertEqual(payload["message_id"], "D2:DJUA-KIN-000001:9IX")
        self.assertIn("battery", payload)
        self.assertIn("solar", payload)
        self.assertIn("ac_load", payload)
        self.assertEqual(
            payload["dc_load"],
            {
                "voltage_v": 12.35,
                "current_a": 3.2,
                "power_w": 39.5,
                "energy_interval_wh": 19.76,
                "measured_count": None,
            },
        )

    def test_count_one_through_four_reconstructs_current_and_power(self):
        expected = {
            1: (3.2, 39.5),
            2: (6.4, 79.0),
            3: (9.6, 118.5),
            4: (12.8, 158.0),
        }
        for count, (current, power) in expected.items():
            with self.subTest(count=count):
                message = parse_d2t2(
                    rewrite_d2t2_fields(D2T2_TYPICAL, dc_measured_count=count)
                )
                self.assertEqual(message.dc_load_measured_count, count)
                backend = normalize_d2t2_to_backend(
                    message,
                    gateway_received_at="2026-01-01T00:00:00+00:00",
                    auth_status=D2AuthStatus.NOT_VERIFIED,
                )
                self.assertEqual(backend["dc_load"]["current_a"], current)
                self.assertEqual(backend["dc_load"]["power_w"], power)
                self.assertEqual(backend["dc_load"]["energy_interval_wh"], 19.76)

    def test_legacy_dc_load_keeps_averages_and_null_count(self):
        message = parse_d2t2(
            rewrite_d2t2_fields(D2T2_TYPICAL, dc_measured_count=0)
        )
        self.assertIsNone(message.dc_load_measured_count)
        backend = normalize_d2t2_to_backend(
            message,
            gateway_received_at="2026-01-01T00:00:00+00:00",
            auth_status=D2AuthStatus.NOT_VERIFIED,
        )
        self.assertEqual(backend["dc_load"]["current_a"], 3.2)
        self.assertEqual(backend["dc_load"]["power_w"], 39.5)
        self.assertIsNone(backend["dc_load"]["measured_count"])

    def test_count_five_is_rejected(self):
        raw = rewrite_d2t2_fields(D2T2_TYPICAL, dc_measured_count=5)
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2t2(raw)
        self.assertEqual(context.exception.code, "OUT_OF_RANGE")

    def test_nonzero_reserved_tail_is_rejected(self):
        raw = rewrite_d2t2_fields(D2T2_TYPICAL, reserved_tail=1)
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2t2(raw)
        self.assertEqual(context.exception.code, "D2T2_RESERVED_BITS")

    def test_positive_count_requires_dc_valid_flag(self):
        raw = rewrite_d2t2_fields(
            D2T2_TYPICAL, dc_measured_count=1, flags=0x007F
        )
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2t2(raw)
        self.assertEqual(context.exception.code, "FLAG_DEPENDENCY")

    def test_dc_energy_is_null_when_energy_flag_is_clear(self):
        raw = rewrite_d2t2_fields(
            D2T2_TYPICAL, flags=0x00FF, dc_energy_raw=0
        )
        message = parse_d2t2(raw)
        backend = normalize_d2t2_to_backend(
            message,
            gateway_received_at="2026-01-01T00:00:00+00:00",
            auth_status=D2AuthStatus.NOT_VERIFIED,
        )
        self.assertIsNone(backend["dc_load"]["energy_interval_wh"])

    def test_development_auth_dash_preserves_absence_as_null(self):
        message = parse_d2t2(D2T2_DEV_EMPTY)
        status = verify_d2t2_security(
            message,
            mode="development",
            key=None,
        )
        self.assertEqual(status, D2AuthStatus.NOT_VERIFIED)
        self.assertEqual(message.dc_load_measured_count, 0)
        payload = normalize_d2t2_to_backend(
            message,
            gateway_received_at="2026-01-01T00:00:00+00:00",
            auth_status=status,
        )
        self.assertIsNone(payload["battery"]["voltage_v"])
        self.assertIsNone(payload["solar"]["energy_interval_wh"])
        self.assertIsNone(payload["ac_load"]["active_power_w"])
        self.assertIsNone(payload["dc_load"]["power_w"])
        self.assertFalse(payload["validity"]["dc_load"])

    def test_present_bad_hmac_is_rejected_in_development_too(self):
        bad = D2T2_TYPICAL[:-1] + "A"
        message = parse_d2t2(bad)
        with self.assertRaises(D2ProtocolError) as context:
            verify_d2t2_security(
                message,
                mode="development",
                key=KEY,
            )
        self.assertEqual(context.exception.code, "AUTH_INVALID")

    def test_short_payload_is_rejected_before_decode(self):
        fields = D2T2_DEV_EMPTY.split(",")
        fields[2] = fields[2][:-1]
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2t2(",".join(fields))
        self.assertEqual(context.exception.code, "D2T2_PAYLOAD_SHAPE")

    def test_wire_alphabet_rejects_non_d2_character(self):
        fields = D2T2_DEV_EMPTY.split(",")
        fields[2] = "+" + fields[2][1:]
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2t2(",".join(fields))
        self.assertEqual(context.exception.code, "D2_CHARSET")


if __name__ == "__main__":
    unittest.main()
