from dataclasses import dataclass
import json


SCHEMA = """
CREATE TABLE IF NOT EXISTS listen_events (
    sequence INTEGER PRIMARY KEY,
    seat TEXT NOT NULL,
    request TEXT NOT NULL,
    edition INTEGER NOT NULL,
    frame INTEGER NOT NULL CHECK (frame > 0),
    operator TEXT NOT NULL,
    sample INTEGER NOT NULL CHECK (sample BETWEEN -127 AND 127),
    origin TEXT NOT NULL,
    UNIQUE (seat, request),
    FOREIGN KEY (seat, edition) REFERENCES installed_editions(seat, edition)
);
"""


@dataclass(frozen=True)
class ListenReceipt:
    seat: str
    request: str
    edition: int
    frame: int
    operator: str
    sample: int
    sequence: int
    origin: dict


def append_listen(db, seat, request, edition, frame, operator, sample, origin):
    cursor = db.execute(
        """INSERT INTO listen_events (seat, request, edition, frame, operator, sample, origin)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (seat, request, edition, frame, operator, sample, json.dumps(origin, sort_keys=True)),
    )
    return ListenReceipt(seat, request, edition, frame, operator, sample, cursor.lastrowid, origin)


def receipt(db, seat, request):
    row = db.execute(
        """SELECT seat, request, edition, frame, operator, sample, sequence, origin
           FROM listen_events WHERE seat = ? AND request = ?""", (seat, request)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["origin"] = json.loads(result["origin"])
    return ListenReceipt(**result)
