from contextlib import closing
from dataclasses import asdict
import argparse
import sqlite3
import threading

from monitor import install, listener, playback, receipts, seats
from monitor.listener import Accepted
from rehearsal_contract import Problem, label
from rehearsal_http import JsonHandler, LocalService, connect, create_schema
from rehearsal_http import LOGGER


def _receipt(db, data):
    seat = label(data.get("seat"), "seat")
    request = label(data.get("request"), "request")
    result = receipts.receipt(db, seat, request)
    if result is None:
        raise Problem(404, "receipt_unavailable", request=request)
    return asdict(result)


class MonitorRequestHandler(JsonHandler):
    operations = {
        ("POST", "/load"): install.load,
        ("POST", "/handover"): seats.handover,
        ("POST", "/listen_frame"): playback.listen_frame,
        ("GET", "/receipt"): _receipt,
    }


def _bind_handler(base, database, device_seat, device_port):
    """Build a handler that routes the bound seat to the listener device."""

    deferred = threading.local()

    def load(db, data):
        return install.load(db, data)

    def listen(db, data):
        if label(data.get("seat"), "seat") != device_seat:
            return playback.listen_frame(db, data)
        # Phase 1 validates and durably accepts on the handler's transaction;
        # phase 2 (device traffic) is deferred until after that transaction commits.
        row = listener.prepare_listen(db, data)
        deferred.action = lambda: listener.listen_after_commit(database, device_port, row)
        return None

    def handover(db, data):
        if label(data.get("seat"), "seat") != device_seat:
            return seats.handover(db, data)
        plan = listener.prepare_handover(db, data)
        deferred.action = lambda: listener.handover_after_commit(database, device_port, plan)
        return None

    def get_receipt(db, data):
        if label(data.get("seat"), "seat") != device_seat:
            return _receipt(db, data)
        result = listener.get_receipt(db, data)
        if result is None:
            raise Problem(404, "receipt_unavailable",
                          request=label(data.get("request"), "request"))
        if result["status"] == "pending":
            raise Accepted(result)
        return result

    class BoundMonitorRequestHandler(base):
        operations = {
            ("POST", "/load"): load,
            ("POST", "/handover"): handover,
            ("POST", "/listen_frame"): listen,
            ("GET", "/receipt"): get_receipt,
        }

        def handle_json(self, method):
            deferred.action = None
            try:
                operation, data = self.read_request(method)
                with closing(connect(self.server.database)) as db, db:
                    db.execute("BEGIN IMMEDIATE" if method == "POST" else "BEGIN")
                    immediate = operation(db, data)
            except Problem as error:
                self.send_result(error.status, error.payload)
                return
            except sqlite3.Error:
                LOGGER.exception("database operation failed")
                self.send_result(500, {"error": "storage_failure"})
                return
            except Accepted as accepted:
                # Phase-1 busy rejection: nothing was deferred.
                self.send_result(202, accepted.payload)
                return

            action = getattr(deferred, "action", None)
            if action is None:
                # Ordinary (non-device) route: send its result right away.
                self.send_result(200, immediate)
                return
            deferred.action = None
            try:
                payload = action()
            except Accepted as accepted:
                self.send_result(202, accepted.payload)
                return
            self.send_result(200, payload)

    return BoundMonitorRequestHandler


def serve_monitor(database, port=0, handler_class=MonitorRequestHandler,
                  device_seat=None, device_port=None):
    with closing(connect(database)) as db:
        create_schema(db, install.SCHEMA, seats.SCHEMA, receipts.SCHEMA)
        if device_seat is not None:
            if device_port is None:
                raise ValueError("device_port is required when device_seat is set")
            create_schema(db, listener.SCHEMA)
            handler_class = _bind_handler(handler_class, database, device_seat, device_port)
    return LocalService(database, port, handler_class)


def main():
    parser = argparse.ArgumentParser(description="榆桥联排离线返听服务")
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--device-seat", help="绑定外接监听器的席位")
    parser.add_argument("--device-port", type=int, help="环回监听器端口")
    args = parser.parse_args()
    with serve_monitor(args.db, args.port, device_seat=args.device_seat,
                       device_port=args.device_port) as server:
        host, port = server.server_address
        print(f"http://{host}:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
