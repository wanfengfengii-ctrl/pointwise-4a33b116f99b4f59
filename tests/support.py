from contextlib import ExitStack, closing
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.parse import urlencode

from monitor.listen_service import MonitorRequestHandler, serve_monitor
from studio.source_service import serve_source


PROGRAM = "rehearsal"
SEAT = "booth"


class HttpService:
    def __init__(self, factory, database, **options):
        self.factory = factory
        self.database = database
        self.options = options

    def __enter__(self):
        self.server = self.factory(self.database, **self.options)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def call(self, endpoint, body=None, **query):
        host, port = self.server.server_address
        path = "/" + endpoint
        if query:
            path += "?" + urlencode(query)
        with closing(HTTPConnection(host, port, timeout=5)) as connection:
            if body is None:
                connection.request("GET", path)
            else:
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                connection.request("POST", path, encoded, {"Content-Type": "application/json"})
            with connection.getresponse() as response:
                return response.status, json.loads(response.read())

    def ok(self, endpoint, body=None, **query):
        status, result = self.call(endpoint, body, **query)
        if status != 200:
            raise AssertionError(f"{endpoint}: {status} {result!r}")
        return result


def _drop_handler(request, dropped):
    class DropAfterCommit(MonitorRequestHandler):
        def send_result(self, status, payload):
            if (self.command == "POST" and self.path == "/listen_frame" and status == 200
                    and payload.get("request") == request and not dropped):
                dropped.append(payload)
                self.close_connection = True
                return
            super().send_result(status, payload)
    return DropAfterCommit


class Bench:
    def __init__(self, drop_request=None):
        self.drop_request = drop_request
        self.dropped = []
        self.source_stack = ExitStack()
        self.monitor_stack = ExitStack()

    def __enter__(self):
        with ExitStack() as stack:
            self.root = Path(stack.enter_context(TemporaryDirectory(prefix="rehearsal-")))
            stack.callback(self.source_stack.close)
            stack.callback(self.monitor_stack.close)
            self.source_db = self.root / "source.sqlite"
            self.monitor_db = self.root / "monitor.sqlite"
            self.restart_source()
            self.restart_monitor(self.drop_request)
            self.cleanup = stack.pop_all()
        return self

    def __exit__(self, *exc):
        self.cleanup.close()

    def stop_source(self):
        self.source_stack.close()

    def restart_source(self):
        self.stop_source()
        self.source = self.source_stack.enter_context(HttpService(serve_source, self.source_db))

    def restart_monitor(self, drop_request=None):
        self.monitor_stack.close()
        handler = MonitorRequestHandler if drop_request is None else _drop_handler(drop_request, self.dropped)
        self.monitor = self.monitor_stack.enter_context(
            HttpService(serve_monitor, self.monitor_db, handler_class=handler)
        )

    def configure(self, **values):
        return self.source.ok("configure", {"program": PROGRAM, **values})

    def record(self, frame, samples):
        return self.source.ok("record_frame", record_request(frame, samples))

    def recorded(self, frame):
        return self.source.ok("record_frame", program=PROGRAM, source_frame=frame)

    def preview(self, revision, frames):
        return self.source.ok("preview", revision_request(revision, source_frames=frames))

    def freeze(self, revision):
        return self.source.ok("freeze", revision_request(revision))

    def publish(self, revision, frames):
        result = self.preview(revision, frames)
        if not result["freezable"]:
            raise AssertionError(f"unresolved sample revision {result!r}")
        return self.freeze(revision)

    def program_audio(self, edition, frame):
        return self.source.ok("program_audio", edition=edition, frame=frame)

    def install(self, frozen):
        return self.monitor.ok("load", {"seat": SEAT, "package": frozen["package"]})

    def handover(self, operator):
        return self.monitor.ok("handover", {"seat": SEAT, "operator": operator})

    def listen(self, request, edition, frame=1):
        return self.monitor.ok("listen_frame", listen_request(request, edition, frame))

    def receipt(self, request):
        return self.monitor.ok("receipt", seat=SEAT, request=request)


class BenchCase(unittest.TestCase):
    drop_request = None

    def setUp(self):
        self.bench = self.enterContext(Bench(self.drop_request))


def record_request(frame, samples):
    return {"program": PROGRAM, "source_frame": frame, "contributions": samples}


def revision_request(revision, **values):
    return {"program": PROGRAM, "revision": revision, **values}


def listen_request(request, edition, frame=1):
    return {"seat": SEAT, "request": request, "edition": edition, "frame": frame}


def scalar(database, statement, parameters=()):
    database_uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as db:
        return db.execute(statement, parameters).fetchone()[0]


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    payload = dict(case_id=case_id, input=inputs, expected=expected, actual=actual,
                   downstream_expected=downstream_expected, downstream_actual=downstream_actual,
                   code_paths=code_paths, oracle=oracle)
    print("POINTWISE_SCENARIO " + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
