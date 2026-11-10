import unittest
from winpilot.toolbox import host_value


class HostBoundaries(unittest.TestCase):
    def test_invalid_ipv4_cannot_fall_back_to_dns(self):
        for value in ('999.999.999.999', '256.1.1.1', '192.168.001.1',
                      '253.253.253.253.', '１２７.０.０.１'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    host_value(value)

    def test_addresses_and_numeric_dns_labels_preserved(self):
        for value in ('192.168.0.1', '0.0.0.0', '255.255.255.255', '::1',
                      '2001:db8::1', '123.example', 'COM1', 'example.com.'):
            with self.subTest(value=value):
                self.assertEqual(host_value(value), value)
