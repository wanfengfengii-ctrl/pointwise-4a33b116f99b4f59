from dataclasses import asdict, dataclass
import json

from mix.preview import PreviewFrame, render_program
from mix.sequence import FrameReference, read_sequence, write_sequence
from mix.validation import validate_sequence
from rehearsal_contract import Problem, array_value, label, position
from studio.programs import get_program


SCHEMA = """
CREATE TABLE IF NOT EXISTS mix_revisions (
    program TEXT NOT NULL REFERENCES programs(program),
    revision TEXT NOT NULL,
    freezable INTEGER NOT NULL CHECK (freezable IN (0, 1)),
    preview_frames TEXT NOT NULL,
    missing_frames TEXT NOT NULL,
    PRIMARY KEY (program, revision)
);
"""


@dataclass(frozen=True)
class MixRevision:
    program: str
    revision: str
    freezable: bool
    frames: tuple[PreviewFrame, ...]
    missing: tuple[FrameReference, ...]

    def payload(self):
        return {
            "program": self.program,
            "revision": self.revision,
            "freezable": self.freezable,
            "frames": [asdict(frame) for frame in self.frames],
            "missing": [asdict(reference) for reference in self.missing],
        }


def _revision_row(db, program, revision):
    return db.execute(
        """SELECT freezable, preview_frames, missing_frames FROM mix_revisions
           WHERE program = ? AND revision = ?""",
        (program, revision),
    ).fetchone()


def preview(db, data):
    program = label(data.get("program"), "program")
    revision = label(data.get("revision"), "revision")
    get_program(db, program)
    source_frames = array_value(data.get("source_frames"), "source_frames")
    references = tuple(FrameReference(index, position(source_frame, "source_frames"))
                       for index, source_frame in enumerate(source_frames, 1))
    prior = _revision_row(db, program, revision)
    if prior is not None and references != read_sequence(db, program, revision):
        raise Problem(409, "revision_sequence_conflict", revision=revision)

    checked = validate_sequence(db, program, references)
    frames = tuple(
        render_program(reference.frame, recorded["origin"],
                       (item["sample"] for item in recorded["contributions"]))
        for reference, recorded in checked.found
    )
    result = MixRevision(program, revision, checked.freezable, frames, checked.missing).payload()
    db.execute(
        """INSERT INTO mix_revisions VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (program, revision) DO UPDATE SET
             freezable = excluded.freezable, preview_frames = excluded.preview_frames,
             missing_frames = excluded.missing_frames""",
        (program, revision, checked.freezable, json.dumps(result["frames"]), json.dumps(result["missing"])),
    )
    if prior is None:
        write_sequence(db, program, revision, references)
    return result


def read_freezable_revision(db, program, revision):
    row = _revision_row(db, program, revision)
    if row is None:
        raise Problem(404, "revision_unavailable", revision=revision)
    if not row["freezable"]:
        raise Problem(409, "revision_not_freezable", revision=revision,
                      missing=json.loads(row["missing_frames"]))
    frames = tuple(PreviewFrame(**frame) for frame in json.loads(row["preview_frames"]))
    return MixRevision(program, revision, True, frames, ())
