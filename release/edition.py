from dataclasses import asdict, dataclass
import json

from release.provenance import FrozenFrameOrigin, read_origin


SCHEMA = """
CREATE TABLE IF NOT EXISTS editions (
    edition INTEGER PRIMARY KEY,
    program TEXT NOT NULL,
    revision TEXT NOT NULL,
    roster TEXT NOT NULL,
    FOREIGN KEY (program, revision) REFERENCES mix_revisions(program, revision)
);
CREATE TABLE IF NOT EXISTS frozen_frames (
    edition INTEGER NOT NULL REFERENCES editions(edition),
    frame INTEGER NOT NULL CHECK (frame > 0),
    program_sample INTEGER NOT NULL CHECK (program_sample BETWEEN -127 AND 127),
    origin TEXT NOT NULL,
    monitor_samples TEXT NOT NULL,
    PRIMARY KEY (edition, frame)
);
"""


@dataclass(frozen=True)
class FrozenFrame:
    frame: int
    program_sample: int
    origin: FrozenFrameOrigin
    monitor_samples: dict[str, int]


@dataclass(frozen=True)
class FrozenEdition:
    edition: int
    program: str
    revision: str
    roster: dict[str, str]
    frames: tuple[FrozenFrame, ...]

    def frame_at(self, frame):
        if 1 <= frame <= len(self.frames):
            return self.frames[frame - 1]
        return None


def write_edition(db, program, revision, roster, frames):
    cursor = db.execute("INSERT INTO editions (program, revision, roster) VALUES (?, ?, ?)",
                        (program, revision, json.dumps(roster)))
    edition_id = cursor.lastrowid
    db.executemany(
        "INSERT INTO frozen_frames VALUES (?, ?, ?, ?, ?)",
        [(edition_id, frame.frame, frame.program_sample, json.dumps(asdict(frame.origin)),
          json.dumps(frame.monitor_samples)) for frame in frames],
    )
    return FrozenEdition(edition_id, program, revision, roster, frames)


def read_edition(db, edition_id):
    header = db.execute("SELECT program, revision, roster FROM editions WHERE edition = ?",
                        (edition_id,)).fetchone()
    if header is None:
        return None
    rows = db.execute(
        """SELECT frame, program_sample, origin, monitor_samples FROM frozen_frames
           WHERE edition = ? ORDER BY frame""",
        (edition_id,),
    )
    frames = tuple(FrozenFrame(row["frame"], row["program_sample"],
                               read_origin(json.loads(row["origin"]), header["program"]),
                               json.loads(row["monitor_samples"])) for row in rows)
    return FrozenEdition(edition_id, header["program"], header["revision"],
                         json.loads(header["roster"]), frames)
