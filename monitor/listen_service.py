from contextlib import closing
from dataclasses import asdict

from monitor import install, playback, receipts, seats
from rehearsal_contract import Problem, label
from rehearsal_http import JsonHandler, LocalService, connect, create_schema, run_service


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


def serve_monitor(database, port=0, handler_class=MonitorRequestHandler):
    with closing(connect(database)) as db:
        create_schema(db, install.SCHEMA, seats.SCHEMA, receipts.SCHEMA)
    return LocalService(database, port, handler_class)


def main():
    run_service(serve_monitor, "榆桥联排离线返听服务", 8002)


if __name__ == "__main__":
    main()
