import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import sqlite3
from urllib.parse import parse_qsl, urlsplit

from rehearsal_contract import Problem, object_value


LOGGER = logging.getLogger("rehearsal.http")


def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(db, *statements):
    db.executescript("BEGIN IMMEDIATE;\n" + "\n".join(statements) + "\nCOMMIT;")


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("repeated field")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


class JsonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_json("GET")

    def do_POST(self):
        self.handle_json("POST")

    def handle_json(self, method):
        try:
            operation, data = self.read_request(method)
            with closing(connect(self.server.database)) as db, db:
                db.execute("BEGIN IMMEDIATE" if method == "POST" else "BEGIN")
                result = operation(db, data)
            status = 200
        except Problem as error:
            status, result = error.status, error.payload
        except sqlite3.Error:
            LOGGER.exception("database operation failed")
            status, result = 500, {"error": "storage_failure"}
        self.send_result(status, result)

    def read_request(self, method):
        try:
            target = urlsplit(self.path)
        except ValueError as error:
            raise Problem(400, "invalid_target") from error
        if target.scheme or target.netloc or target.fragment:
            raise Problem(400, "invalid_target")
        operation = self.operations.get((method, target.path))
        if operation is None:
            raise Problem(404, "unknown_endpoint")
        if method == "POST":
            if target.query:
                raise Problem(400, "unexpected_query")
            return operation, self.read_body()
        try:
            fields = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True, errors="strict")
            return operation, _unique_fields(fields)
        except ValueError as error:
            raise Problem(400, "invalid_query") from error

    def read_body(self):
        if self.headers.get_content_type() != "application/json":
            raise Problem(415, "json_required")
        try:
            length = int(self.headers.get("Content-Length", ""))
            if length < 0:
                raise ValueError("negative length")
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise ValueError("incomplete body")
            value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_fields,
                               parse_constant=_reject_constant)
        except (ValueError, OverflowError, RecursionError) as error:
            raise Problem(400, "invalid_json") from error
        return object_value(value, "body")

    def send_result(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, message, *args):
        LOGGER.info(message, *args)


class LocalService(ThreadingHTTPServer):
    def __init__(self, database, port, handler):
        self.database = database
        super().__init__(("127.0.0.1", port), handler)


def run_service(factory, description, default_port):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()
    with factory(args.db, args.port) as server:
        host, port = server.server_address
        print(f"http://{host}:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return
