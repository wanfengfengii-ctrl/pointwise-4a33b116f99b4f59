from collections import defaultdict

from mix.preview import clamp_sample
from mix.revisions import read_freezable_revision
from mix.sequence import read_sequence
from mix.validation import validate_sequence
from rehearsal_contract import Problem, label
from release.distribution import encode_edition
from release.edition import FrozenFrame, write_edition
from release.provenance import build_origins
from studio.programs import get_program
from studio.roster import list_members


def _monitor_samples(contributions, roster):
    by_speaker = defaultdict(int)
    for contribution in contributions:
        by_speaker[contribution["speaker"]] += contribution["sample"]
    total = sum(by_speaker.values())
    return {speaker: clamp_sample(total - by_speaker.get(speaker, 0)) for speaker in roster}


def freeze(db, data):
    program = label(data.get("program"), "program")
    revision_id = label(data.get("revision"), "revision")
    get_program(db, program)
    revision = read_freezable_revision(db, program, revision_id)
    checked = validate_sequence(db, program, read_sequence(db, program, revision_id))
    if not checked.freezable:
        raise Problem(409, "revision_not_freezable", revision=revision_id,
                      missing=[{"frame": item.frame, "source_frame": item.source_frame} for item in checked.missing])

    roster = {member.speaker: member.name for member in list_members(db, program)}
    origins = build_origins(program, checked.found)
    frames = []
    for preview, (reference, recorded) in zip(revision.frames, checked.found, strict=True):
        origin = origins[reference.frame]
        frames.append(FrozenFrame(reference.frame, preview.sample, origin,
                                  _monitor_samples(recorded["contributions"], roster)))
    edition = write_edition(db, program, revision_id, roster, tuple(frames))
    return {"edition": edition.edition, "package": encode_edition(edition)}
