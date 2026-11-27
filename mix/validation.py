from dataclasses import dataclass

from capture.intake import read_recorded_frame
from mix.sequence import FrameReference


@dataclass(frozen=True)
class RevisionValidation:
    found: tuple[tuple[FrameReference, dict], ...]
    missing: tuple[FrameReference, ...]

    @property
    def freezable(self):
        return not self.missing


def validate_sequence(db, program, references):
    found = []
    missing = []
    for reference in references:
        recorded = read_recorded_frame(db, program, reference.source_frame)
        if recorded is None:
            missing.append(reference)
        else:
            found.append((reference, recorded))
    return RevisionValidation(tuple(found), tuple(missing))
