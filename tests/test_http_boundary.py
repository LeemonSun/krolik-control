import copy
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from winpilot.demo import Demo, INFO
from winpilot.server import Application, create_server


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Application(Demo(), Path(__file__).resolve().parents[1] / 'ui', self.tmp.name, True)
        self.app.info = copy.deepcopy(INFO)
        self.server = create_server(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.close_requested = True
        self.server.shutdown(); self.server.server_close()
        self.app.pc.close(); self.app.toolbox.close()
        self.tmp.cleanup()

    def request(self, body=b'{}', headers=None, target='/api/workspace'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        actual = {'X-WinPilot-Token': self.app.token, 'Content-Type': 'application/json'}
        actual.update(headers or {})
        connection.request('POST', target, body, actual)
        result = connection.getresponse()
        value = result.status, result.read()
        connection.close()
        return value

    def raw_request(self, extra, body=b'{}'):
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as connection:
            request = (f'POST /api/activate HTTP/1.0\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                       f'X-WinPilot-Token: {self.app.token}\r\nContent-Type: application/json\r\n' + extra + '\r\n').encode('ascii') + body
            connection.sendall(request)
            return connection.recv(1024).split(b'\r\n')[0]

    def test_valid_request_still_works(self):
        self.assertEqual(self.request(target='/api/activate')[0], 200)
        self.assertEqual(self.app.activation, 1)

    def test_cross_origin_and_invalid_token_rejected_before_action(self):
        self.assertEqual(self.request(headers={'Origin': 'https://example.com'}, target='/api/activate')[0], 403)
        self.assertEqual(self.request(headers={'X-WinPilot-Token': 'wrong'}, target='/api/activate')[0], 403)
        self.assertEqual(self.app.activation, 0)

    def test_duplicate_length_rejected(self):
        self.assertIn(b'400', self.raw_request('Content-Length: 2\r\nContent-Length: 2\r\n'))

    def test_transfer_encoding_rejected(self):
        self.assertIn(b'400', self.raw_request('Content-Length: 2\r\nTransfer-Encoding: chunked\r\n'))

    def test_duplicate_host_rejected(self):
        self.assertIn(b'403', self.raw_request(f'Content-Length: 2\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'))

    def test_duplicate_keys_and_nonfinite_numbers_never_mutate(self):
        original = copy.deepcopy(self.app.workspace.value)
        for value in (b'{"revision":0,"revision":1}', b'{"revision":NaN}', b'{"revision":Infinity}', b'{"revision":-Infinity}'):
            self.assertEqual(self.request(body=value)[0], 400)
        self.assertEqual(self.app.workspace.value, original)

    def test_deep_invalid_json_returns_error(self):
        body = b'{"revision":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'
        self.assertEqual(self.request(body=body)[0], 400)
        self.assertEqual(self.request(target='/api/activate')[0], 200)

    def test_additional_lifetime_connections_are_refused(self):
        self.app.lifetime_connections = 4
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request('GET', '/api/lifetime', headers={'X-WinPilot-Token': self.app.token})
        response = connection.getresponse()
        self.assertEqual(response.status, 429)
        response.read(); connection.close()

    def test_partial_body_has_finite_timeout(self):
        # Socket stalls must result in HTTP 408 rather than an unbounded handler.
        original = socket.socket.settimeout
        def short_timeout(sock, seconds):
            return original(sock, min(seconds, .1) if seconds is not None else seconds)
        with patch.object(socket.socket, 'settimeout', short_timeout):
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2) as connection:
                original(connection, 2)
                request = (f'POST /api/activate HTTP/1.0\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                           f'X-WinPilot-Token: {self.app.token}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{').encode()
                connection.sendall(request)
                self.assertIn(b'408', connection.recv(1024).split(b'\r\n')[0])
        self.assertEqual(self.app.activation, 0)

    def test_worker_slots_return_after_error(self):
        before = self.server.slots._value
        self.assertEqual(self.request(target='/api/activate')[0], 200)
        # A completed handler's finally releases its capacity.
        import time
        limit = time.monotonic() + 2
        while self.server.slots._value != before and time.monotonic() < limit:
            time.sleep(.01)
        self.assertEqual(self.server.slots._value, before)
