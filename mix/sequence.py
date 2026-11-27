from dataclasses import dataclass


SCHEMA = """
CREATE TABLE IF NOT EXISTS mix_sequence (
    program TEXT NOT NULL,
    revision TEXT NOT NULL,
    frame INTEGER NOT NULL CHECK (frame > 0),
    source_frame INTEGER NOT NULL CHECK (source_frame > 0),
    PRIMARY KEY (program, revision, frame),
    FOREIGN KEY (program, revision) REFERENCES mix_revisions(program, revision)
);
"""


@dataclass(frozen=True)
class FrameReference:
    frame: int
    source_frame: int


def write_sequence(db, program, revision, references):
    db.executemany(
        "INSERT INTO mix_sequence VALUES (?, ?, ?, ?)",
        [(program, revision, reference.frame, reference.source_frame) for reference in references],
    )


def read_sequence(db, program, revision):
    rows = db.execute(
        """SELECT frame, source_frame FROM mix_sequence
           WHERE program = ? AND revision = ? ORDER BY frame""",
        (program, revision),
    )
    return tuple(FrameReference(**dict(row)) for row in rows)
