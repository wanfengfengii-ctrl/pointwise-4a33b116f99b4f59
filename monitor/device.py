"""HTTP client for the single external listener device.

The seat side may only use the two device entry points described in
LISTENER.md: GET /state and POST /operate.  Every call opens a fresh
loopback connection because the device may close a connection after a
committed operation whose reply was dropped.
"""

from contextlib import closing
from http.client import HTTPConnection
import json


class DeviceError(Exception):
    """Base class for device side failures."""


class DeviceUnavailable(DeviceError):
    """The device cannot currently confirm anything (503, timeout, reset)."""


class DeviceConflict(DeviceError):
    """The submitted expected number did not match the current device number."""

    def __init__(self, payload=None):
        super().__init__("operation_number_conflict")
        self.payload = payload


class ListenerDevice:
    def __init__(self, port, host="127.0.0.1", timeout=5):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _call(self, method, path, body=None):
        try:
            with closing(HTTPConnection(self.host, self.port, timeout=self.timeout)) as connection:
                if body is None:
                    connection.request(method, path)
                else:
                    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
                    connection.request(method, path, encoded,
                                       {"Content-Type": "application/json"})
                with connection.getresponse() as response:
                    raw = response.read()
                    status = response.status
                    payload = json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, ValueError) as error:
            # Connection refused/reset/timeout, closed connection without a
            # reply, or an undecodable body all leave the outcome unknown.
            raise DeviceUnavailable(str(error)) from error
        if status == 200:
            return payload
        if status == 409:
            raise DeviceConflict(payload)
        raise DeviceUnavailable(payload)

    def state(self):
        return self._call("GET", "/state")

    def operate(self, expected, operation, kind, sample=None):
        body = {"expected": expected, "operation": operation, "kind": kind}
        if kind == "sound":
            body["sample"] = sample
        return self._call("POST", "/operate", body)
