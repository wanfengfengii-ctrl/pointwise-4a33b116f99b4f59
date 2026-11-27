from dataclasses import dataclass
import json

from rehearsal_contract import Problem, label
from release.distribution import decode_edition, encode_edition
from release.edition import FrozenEdition


SCHEMA = """
CREATE TABLE IF NOT EXISTS installed_editions (
    seat TEXT NOT NULL,
    edition INTEGER NOT NULL,
    package TEXT NOT NULL,
    PRIMARY KEY (seat, edition)
);
CREATE TABLE IF NOT EXISTS active_editions (
    seat TEXT PRIMARY KEY,
    edition INTEGER NOT NULL,
    FOREIGN KEY (seat, edition) REFERENCES installed_editions(seat, edition)
);
"""


@dataclass(frozen=True)
class InstalledEdition:
    seat: str
    snapshot: FrozenEdition


def load(db, data):
    seat = label(data.get("seat"), "seat")
    edition = decode_edition(data.get("package"))
    package = json.dumps(encode_edition(edition), sort_keys=True, separators=(",", ":"))
    prior = db.execute("SELECT package FROM installed_editions WHERE seat = ? AND edition = ?",
                       (seat, edition.edition)).fetchone()
    if prior is not None and prior["package"] != package:
        raise Problem(409, "edition_conflict", edition=edition.edition)
    if prior is None:
        db.execute("INSERT INTO installed_editions VALUES (?, ?, ?)", (seat, edition.edition, package))
    db.execute(
        """INSERT INTO active_editions VALUES (?, ?)
           ON CONFLICT (seat) DO UPDATE SET edition = excluded.edition""",
        (seat, edition.edition),
    )
    return {"seat": seat, "edition": edition.edition, "revision": edition.revision}


def read_installed_edition(db, seat, edition=None):
    if edition is None:
        row = db.execute(
            """SELECT i.package FROM active_editions AS a JOIN installed_editions AS i
               ON a.seat = i.seat AND a.edition = i.edition WHERE a.seat = ?""", (seat,)
        ).fetchone()
    else:
        row = db.execute("SELECT package FROM installed_editions WHERE seat = ? AND edition = ?",
                         (seat, edition)).fetchone()
    if row is None:
        return None
    return InstalledEdition(seat, decode_edition(json.loads(row["package"])))
