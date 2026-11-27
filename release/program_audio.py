from dataclasses import asdict

from rehearsal_contract import Problem
from release.edition import read_edition


def program_audio(db, edition_id, frame_number):
    edition = read_edition(db, edition_id)
    if edition is None:
        raise Problem(404, "edition_unavailable", edition=edition_id)
    frame = edition.frame_at(frame_number)
    if frame is None:
        raise Problem(404, "frame_unavailable", edition=edition_id, frame=frame_number)
    return {"edition": edition.edition, "frame": frame.frame, "sample": frame.program_sample,
            "origin": asdict(frame.origin)}
