from contextlib import closing
from http.client import RemoteDisconnected
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import unittest

from rehearsal_contract import Problem, invalid, label
from rehearsal_http import JsonHandler, LocalService, connect, create_schema
from tests.support import HttpService


SCHEMA = """
CREATE TABLE IF NOT EXISTS listener_head (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    number INTEGER NOT NULL,
    operation TEXT,
    kind TEXT,
    sample INTEGER
);
INSERT OR IGNORE INTO listener_head (singleton, number) VALUES (1, 0);
"""


def state(db, data):
    row = db.execute('SELECT number, operation, kind, sample FROM listener_head').fetchone()
    last = None if not row['number'] else {key: row[key] for key in ('operation', 'kind', 'sample')}
    return {'number': row['number'], 'last': last}


def operate(db, data):
    expected = data.get('expected')
    if type(expected) is not int or not 0 <= expected < 2**63 - 1:
        raise invalid('expected')
    operation = label(data.get('operation'), 'operation')
    kind = data.get('kind')
    sample = data.get('sample')
    if kind == 'sound':
        if type(sample) is not int or not -127 <= sample <= 127:
            raise invalid('sample')
    elif kind != 'advance':
        raise invalid('kind')
    elif sample is not None:
        raise invalid('sample')
    changed = db.execute(
        'UPDATE listener_head SET number = number + 1, operation = ?, kind = ?, sample = ? WHERE number = ?',
        (operation, kind, sample, expected),
    ).rowcount
    if not changed:
        raise Problem(409, 'operation_number_conflict')
    return state(db, {})


class DeviceControls:
    def __init__(self):
        self.lock = Lock()
        self._defer_sound = False
        self._drop_commit = False
        self._unavailable = False
        self._deferred = []
        self._sounds = []

    def defer_next_sound(self):
        with self.lock:
            self._defer_sound = True

    def drop_next_commit(self):
        with self.lock:
            self._drop_commit = True

    def set_unavailable(self, value):
        with self.lock:
            self._unavailable = value

    def before(self, method, data):
        with self.lock:
            if self._unavailable:
                raise Problem(503, 'device_unavailable')
            if method == 'POST' and data.get('kind') == 'sound' and self._defer_sound:
                self._defer_sound = False
                self._unavailable = True
                self._deferred.append(data.copy())
                raise Problem(503, 'delivery_delayed')

    def committed(self, payload):
        with self.lock:
            if payload['last']['kind'] == 'sound':
                self._sounds.append({'number': payload['number'], **payload['last']})
            drop = self._drop_commit
            self._drop_commit = False
            if drop:
                self._unavailable = True
            return drop

    def take_deferred(self):
        with self.lock:
            return self._deferred.pop(0)

    def sounds(self):
        with self.lock:
            return sorted((entry.copy() for entry in self._sounds), key=lambda entry: entry['number'])


class DeviceHandler(JsonHandler):
    operations = {('GET', '/state'): state, ('POST', '/operate'): operate}

    def read_request(self, method):
        operation, data = super().read_request(method)
        self.server.controls.before(method, data)
        return operation, data

    def send_result(self, status, payload):
        if self.command == 'POST' and status == 200 and self.server.controls.committed(payload):
            self.close_connection = True
            return
        super().send_result(status, payload)


def serve_device(database, port=0, controls=None):
    with closing(connect(database)) as db:
        create_schema(db, SCHEMA)
    server = LocalService(database, port, DeviceHandler)
    server.controls = DeviceControls() if controls is None else controls
    return server


class ListenerDeviceTests(unittest.TestCase):
    def test_first_device_operation_wins_even_when_delivery_is_delayed(self):
        for advance_first in (False, True):
            with self.subTest(advance_first=advance_first), TemporaryDirectory() as root:
                controls = DeviceControls()
                database = Path(root) / 'device.sqlite'
                sound = dict(expected=0, operation='old-sound', kind='sound', sample=25)
                advance = dict(expected=0, operation='silent', kind='advance')
                with HttpService(serve_device, database, controls=controls) as device:
                    self.assertEqual(device.ok('state'), {'number': 0, 'last': None})
                    controls.defer_next_sound()
                    self.assertEqual(device.call('operate', sound)[0], 503)
                    self.assertEqual(device.call('state')[0], 503)
                    controls.set_unavailable(False)
                    self.assertEqual(device.ok('state'), {'number': 0, 'last': None})
                    delayed = controls.take_deferred()
                    if advance_first:
                        winner = device.ok('operate', advance)
                        self.assertEqual(device.call('operate', delayed)[0], 409)
                        self.assertEqual(controls.sounds(), [])
                        self.assertEqual(winner['last'], {'operation': 'silent', 'kind': 'advance', 'sample': None})
                    else:
                        winner = device.ok('operate', delayed)
                        self.assertEqual(device.call('operate', advance)[0], 409)
                        self.assertEqual(controls.sounds(), [{'number': 1, 'operation': 'old-sound',
                                                              'kind': 'sound', 'sample': 25}])
                    self.assertEqual(winner['number'], 1)
                    self.assertEqual(device.ok('state'), winner)

    def test_commit_can_outlive_response_and_only_head_is_queryable(self):
        with TemporaryDirectory() as root:
            database = Path(root) / 'device.sqlite'
            controls = DeviceControls()
            old = dict(expected=0, operation='q', kind='sound', sample=25)
            with HttpService(serve_device, database, controls=controls) as device:
                controls.drop_next_commit()
                with self.assertRaises(RemoteDisconnected):
                    device.call('operate', old)
                self.assertEqual(device.call('state')[0], 503)
            controls.set_unavailable(False)
            with HttpService(serve_device, database, controls=controls) as device:
                self.assertEqual(device.ok('state'), {'number': 1, 'last': {'operation': 'q',
                                                                           'kind': 'sound', 'sample': 25}})
                self.assertEqual(device.call('operate', old)[0], 409)
                new = device.ok('operate', dict(expected=1, operation='r', kind='sound', sample=-15))
                self.assertEqual(new, {'number': 2, 'last': {'operation': 'r', 'kind': 'sound', 'sample': -15}})
                self.assertEqual(device.ok('state'), new)
                self.assertEqual([entry['sample'] for entry in controls.sounds()], [25, -15])


if __name__ == '__main__':
    unittest.main()
