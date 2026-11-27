"""Bound-seat listener orchestration.

One seat is bound to one external listener device.  A listen is accepted
against the operator and loaded package at acceptance time, then driven on
the device through its two HTTP entry points.  The device only keeps its
last result, so every terminal fact (the original number, operator, sample,
device operation/number and recording origin) is fixed in the seat database
before a later device operation can overwrite it.

At most one accepted-but-unverified device listen exists per seat.

Two-phase rule.  The HTTP handler already owns an open ``BEGIN IMMEDIATE``
transaction on its own connection.  The ``prepare_*`` functions do all
validation and durable acceptance on that connection and return once the
handler commits.  Only then do the ``*_after_commit`` helpers touch the
device and open short-lived connections of their own, so device HTTP traffic
never holds a seat-database write lock.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict

from monitor.device import DeviceConflict, DeviceUnavailable, ListenerDevice
from monitor.playback import resolve_listen_target
from monitor.receipts import append_listen, receipt
from rehearsal_contract import Problem, label, position
from release.distribution import decode_edition


# A terminal head cannot be ours forever; stop re-reading once the head has
# advanced this many times during a single reconciliation.
MAX_ROUNDS = 25


class Accepted(Exception):
    """Carries a 202 payload (pending or busy) back to the HTTP handler."""

    def __init__(self, payload):
        super().__init__(payload["status"])
        self.payload = payload


SCHEMA = """
CREATE TABLE IF NOT EXISTS device_listens (
    seat TEXT NOT NULL,
    request TEXT NOT NULL,
    edition INTEGER NOT NULL,
    frame INTEGER NOT NULL CHECK (frame > 0),
    operator TEXT NOT NULL,
    sample INTEGER NOT NULL CHECK (sample BETWEEN -127 AND 127),
    origin TEXT NOT NULL,
    operation TEXT NOT NULL,
    expected_number INTEGER NOT NULL CHECK (expected_number >= 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'played', 'stopped')),
    device_number INTEGER,
    stop_operation TEXT,
    PRIMARY KEY (seat, request)
);
CREATE TABLE IF NOT EXISTS handover_requests (
    seat TEXT NOT NULL,
    request TEXT NOT NULL,
    operator TEXT NOT NULL,
    edition INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed')),
    PRIMARY KEY (seat, request)
);
"""


# --------------------------------------------------------------------------- #
# Connections and row helpers.
# --------------------------------------------------------------------------- #

def _connect(database):
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _row(db, seat, request):
    return db.execute(
        "SELECT * FROM device_listens WHERE seat = ? AND request = ?", (seat, request)
    ).fetchone()


def _pending_row(db, seat):
    return db.execute(
        "SELECT * FROM device_listens WHERE seat = ? AND status = 'pending'", (seat,)
    ).fetchone()


def _handover_row(db, seat, request):
    return db.execute(
        "SELECT * FROM handover_requests WHERE seat = ? AND request = ?", (seat, request)
    ).fetchone()


def _active_installation(db, seat):
    row = db.execute(
        """SELECT i.package FROM active_editions AS a JOIN installed_editions AS i
           ON a.seat = i.seat AND a.edition = i.edition WHERE a.seat = ?""",
        (seat,),
    ).fetchone()
    if row is None:
        return None
    edition = decode_edition(json.loads(row["package"]))
    return {"edition": edition.edition, "roster": edition.roster}


# --------------------------------------------------------------------------- #
# Reconciliation writes (own connection; only reached after commit).
# --------------------------------------------------------------------------- #

def _mark_played(database, row, number):
    """Fix the played outcome and issue the first receipt in one transaction."""
    with closing(_connect(database)) as db, db:
        current = _row(db, row["seat"], row["request"])
        if current is None or current["status"] != "pending":
            return
        # The V1 first receipt is created only once the sound really plays.
        append_listen(db, row["seat"], row["request"], row["edition"], row["frame"],
                      row["operator"], row["sample"], json.loads(row["origin"]))
        db.execute(
            "UPDATE device_listens SET status = 'played', device_number = ? "
            "WHERE seat = ? AND request = ?",
            (number, row["seat"], row["request"]),
        )


def _mark_stopped(database, row, number, stop_operation):
    with closing(_connect(database)) as db, db:
        current = _row(db, row["seat"], row["request"])
        if current is None or current["status"] != "pending":
            return
        db.execute(
            "UPDATE device_listens SET status = 'stopped', device_number = ?, stop_operation = ? "
            "WHERE seat = ? AND request = ?",
            (number, stop_operation, row["seat"], row["request"]),
        )


def _refresh(database, seat, request):
    with closing(_connect(database)) as db:
        return _row(db, seat, request)


def _set_operator(database, seat, operator):
    with closing(_connect(database)) as db, db:
        db.execute(
            """INSERT INTO seats VALUES (?, ?)
               ON CONFLICT (seat) DO UPDATE SET operator = excluded.operator""",
            (seat, operator),
        )


def _upsert_handover(database, seat, request, operator, edition, status):
    with closing(_connect(database)) as db, db:
        db.execute(
            """INSERT INTO handover_requests VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (seat, request) DO UPDATE SET status = excluded.status""",
            (seat, request, operator, edition, status),
        )


# --------------------------------------------------------------------------- #
# Deterministic operation identifiers.
# --------------------------------------------------------------------------- #

def _digest(prefix, seat, request):
    digest = hashlib.sha1(f"{seat}\x1f{request}".encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def sound_operation(seat, request):
    return _digest("listen", seat, request)


def stop_operation(seat, request):
    return _digest("stop", seat, request)


# --------------------------------------------------------------------------- #
# Responses.
# --------------------------------------------------------------------------- #

def _played_payload(db, row):
    prior = receipt(db, row["seat"], row["request"])
    return {
        "seat": row["seat"],
        "edition": row["edition"],
        "frame": row["frame"],
        "request": row["request"],
        "status": "played",
        "operator": row["operator"],
        "sample": row["sample"],
        "sequence": prior.sequence,
        "origin": json.loads(row["origin"]),
        "device_number": row["device_number"],
    }


def _stopped_payload(row):
    return {
        "seat": row["seat"],
        "edition": row["edition"],
        "frame": row["frame"],
        "request": row["request"],
        "status": "stopped",
    }


def _pending_payload(row):
    return {"seat": row["seat"], "request": row["request"], "status": "pending"}


def _terminal_payload(db, row):
    if row["status"] == "stopped":
        return _stopped_payload(row)
    return _played_payload(db, row)


# --------------------------------------------------------------------------- #
# Device reconciliation.
# --------------------------------------------------------------------------- #

def _head_holds(row, head, operation_field="operation"):
    last = head["last"]
    return last is not None and last["operation"] == row[operation_field]


def drive_sound(database, device, row):
    """Bring a pending sound request to a terminal played result, if confirmable."""
    expected = row["expected_number"]
    for _ in range(MAX_ROUNDS):
        try:
            if expected is None:
                head = device.state()
                if _head_holds(row, head):
                    _mark_played(database, row, head["number"])
                    return
                if row["stop_operation"] is not None and _head_holds(row, head, "stop_operation"):
                    _mark_stopped(database, row, head["number"], row["stop_operation"])
                    return
                expected = head["number"]
            result = device.operate(expected, row["operation"], "sound", row["sample"])
            _mark_played(database, row, result["number"])
            return
        except DeviceConflict:
            # A 409 body only names the error; the current head must be read.
            try:
                head = device.state()
            except DeviceUnavailable:
                return
            if _head_holds(row, head):
                _mark_played(database, row, head["number"])
                return
            if row["stop_operation"] is not None and _head_holds(row, head, "stop_operation"):
                _mark_stopped(database, row, head["number"], row["stop_operation"])
                return
            expected = head["number"]
        except DeviceUnavailable:
            return


def drive_stop(database, device, row):
    """Guarantee the pending sound can no longer play before a handover."""
    stop_op = row["stop_operation"] or stop_operation(row["seat"], row["request"])
    expected = row["expected_number"]
    for _ in range(MAX_ROUNDS):
        try:
            if expected is None:
                head = device.state()
                if _head_holds(row, head):
                    _mark_played(database, row, head["number"])
                    return
                if _head_holds(row, head, "stop_operation"):
                    _mark_stopped(database, row, head["number"], stop_op)
                    return
                expected = head["number"]
            result = device.operate(expected, stop_op, "advance")
            _mark_stopped(database, row, result["number"], stop_op)
            return
        except DeviceConflict:
            # A 409 body only names the error; the current head must be read.
            try:
                head = device.state()
            except DeviceUnavailable:
                return
            if _head_holds(row, head):
                _mark_played(database, row, head["number"])
                return
            if _head_holds(row, head, "stop_operation"):
                _mark_stopped(database, row, head["number"], stop_op)
                return
            expected = head["number"]
        except DeviceUnavailable:
            return


# --------------------------------------------------------------------------- #
# listen_frame: phase 1 runs on the handler's open transaction.
# --------------------------------------------------------------------------- #

def prepare_listen(db, data):
    """Validate and durably accept a listen; return the persisted row."""
    seat = label(data.get("seat"), "seat")
    request = label(data.get("request"), "request")
    existing = _row(db, seat, request)
    if existing is not None:
        edition = data.get("edition")
        frame = data.get("frame")
        if not (type(edition) is int and type(frame) is int
                and (existing["edition"], existing["frame"]) == (edition, frame)):
            raise Problem(409, "request_conflict", request=request)
        return existing

    other = _pending_row(db, seat)
    if other is not None:
        # Another accepted request is still unverified; retry later.
        raise Accepted({"seat": seat, "request": request, "status": "busy"})

    edition = position(data.get("edition"), "edition")
    frame_number = position(data.get("frame"), "frame")
    frame, operator = resolve_listen_target(db, seat, edition, frame_number)
    sample = frame.monitor_samples[operator]
    origin = json.dumps(asdict(frame.origin), sort_keys=True)
    operation = sound_operation(seat, request)
    db.execute(
        "INSERT INTO device_listens (seat, request, edition, frame, operator, sample, "
        "origin, operation, expected_number, status, device_number, stop_operation) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', NULL, NULL)",
        (seat, request, edition, frame_number, operator, sample, origin, operation),
    )
    return _row(db, seat, request)


def listen_after_commit(database, device_port, row):
    """Phase 2: drive the device, then build a terminal or pending response."""
    seat, request = row["seat"], row["request"]
    if row["status"] != "pending":
        with closing(_connect(database)) as db:
            return _terminal_payload(db, row)
    device = ListenerDevice(device_port)
    drive_sound(database, device, row)
    refreshed = _refresh(database, seat, request)
    if refreshed["status"] == "pending":
        raise Accepted(_pending_payload(refreshed))
    with closing(_connect(database)) as db:
        return _terminal_payload(db, refreshed)


# --------------------------------------------------------------------------- #
# handover: phase 1 runs on the handler's open transaction.
# --------------------------------------------------------------------------- #

def prepare_handover(db, data):
    seat = label(data.get("seat"), "seat")
    request = label(data.get("request"), "request")
    operator = label(data.get("operator"), "operator")
    prior = _handover_row(db, seat, request)
    if prior is not None and prior["operator"] != operator:
        raise Problem(409, "request_conflict", request=request)
    if prior is None:
        installed = _active_installation(db, seat)
        if installed is None:
            raise Problem(404, "seat_unloaded", seat=seat)
        if operator not in installed["roster"]:
            raise Problem(400, "operator_not_in_roster", operator=operator)
        edition = installed["edition"]
    else:
        edition = prior["edition"]
    return {"seat": seat, "request": request, "operator": operator, "edition": edition}


def handover_after_commit(database, device_port, plan):
    seat, request = plan["seat"], plan["request"]
    operator, edition = plan["operator"], plan["edition"]

    with closing(_connect(database)) as db:
        prior = _handover_row(db, seat, request)
        if prior is not None and prior["status"] == "completed":
            return {"seat": seat, "operator": operator, "edition": edition,
                    "request": request, "status": "completed"}
        pending = _pending_row(db, seat)

    # The old request must be known played or stopped before the seat moves.
    if pending is not None:
        device = ListenerDevice(device_port)
        drive_stop(database, device, pending)
        refreshed = _refresh(database, seat, pending["request"])
        if refreshed["status"] == "pending":
            _upsert_handover(database, seat, request, operator, edition, "pending")
            raise Accepted({"seat": seat, "request": request, "status": "pending"})

    _set_operator(database, seat, operator)
    _upsert_handover(database, seat, request, operator, edition, "completed")
    return {"seat": seat, "operator": operator, "edition": edition,
            "request": request, "status": "completed"}


def get_receipt(db, data):
    """Read-only lookup; never drives the device and never produces a sound."""
    seat = label(data.get("seat"), "seat")
    request = label(data.get("request"), "request")
    row = _row(db, seat, request)
    if row is None:
        return None
    if row["status"] == "pending":
        return _pending_payload(row)
    return _terminal_payload(db, row)
