from dataclasses import dataclass

from monitor.install import read_installed_edition
from rehearsal_contract import Problem, label


SCHEMA = """
CREATE TABLE IF NOT EXISTS seats (
    seat TEXT PRIMARY KEY,
    operator TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Seat:
    seat: str
    operator: str


def handover(db, data):
    seat = label(data.get("seat"), "seat")
    operator = label(data.get("operator"), "operator")
    installed = read_installed_edition(db, seat)
    if installed is None:
        raise Problem(404, "seat_unloaded", seat=seat)
    if operator not in installed.snapshot.roster:
        raise Problem(400, "operator_not_in_roster", operator=operator)
    db.execute(
        """INSERT INTO seats VALUES (?, ?)
           ON CONFLICT (seat) DO UPDATE SET operator = excluded.operator""", (seat, operator)
    )
    return {"seat": seat, "operator": operator, "edition": installed.snapshot.edition}


def read_operator(db, seat):
    row = db.execute("SELECT seat, operator FROM seats WHERE seat = ?", (seat,)).fetchone()
    return None if row is None else Seat(**dict(row))
