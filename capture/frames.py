from dataclasses import dataclass


SCHEMA = """
CREATE TABLE IF NOT EXISTS recorded_frames (
    program TEXT NOT NULL REFERENCES programs(program),
    source_frame INTEGER NOT NULL CHECK (source_frame > 0),
    PRIMARY KEY (program, source_frame)
);
"""


@dataclass(frozen=True)
class RecordedFrame:
    program: str
    source_frame: int


def insert_frame(db, frame):
    db.execute("INSERT INTO recorded_frames VALUES (?, ?)", (frame.program, frame.source_frame))


def read_frame(db, program, source_frame):
    row = db.execute(
        "SELECT program, source_frame FROM recorded_frames WHERE program = ? AND source_frame = ?",
        (program, source_frame),
    ).fetchone()
    return None if row is None else RecordedFrame(**dict(row))
