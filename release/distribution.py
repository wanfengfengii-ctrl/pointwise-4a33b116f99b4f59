from dataclasses import asdict

from rehearsal_contract import Problem, array_value, invalid, label, object_value, position
from release.edition import FrozenEdition, FrozenFrame
from release.provenance import read_origin


VERSION = 1


def encode_edition(edition):
    return {
        "version": VERSION,
        "edition": edition.edition,
        "program": edition.program,
        "revision": edition.revision,
        "roster": dict(edition.roster),
        "frames": [asdict(frame) for frame in edition.frames],
    }


def _sample(value, field):
    if type(value) is not int or not -127 <= value <= 127:
        raise invalid(field)
    return value


def _decode(raw):
    package = object_value(raw, "package")
    version = package.get("version")
    if type(version) is not int or version != VERSION:
        raise invalid("version")
    edition = position(package.get("edition"), "edition")
    program = label(package.get("program"), "program")
    revision = label(package.get("revision"), "revision")
    roster = {label(speaker, "roster.speaker"): label(name, "roster.name")
              for speaker, name in object_value(package.get("roster"), "roster").items()}
    if not roster:
        raise invalid("roster")

    frames = []
    by_source_frame = {}
    by_recording_receipt = {}
    for index, raw_frame in enumerate(array_value(package.get("frames"), "frames"), 1):
        frame = object_value(raw_frame, "frames.item")
        if position(frame.get("frame"), "frame") != index:
            raise invalid("frame")
        origin = read_origin(frame.get("origin"), program)
        programme_sound = _sample(frame.get("program_sample"), "program_sample")
        samples = object_value(frame.get("monitor_samples"), "monitor_samples")
        if samples.keys() != roster.keys():
            raise invalid("monitor_samples")
        samples = {speaker: _sample(value, "monitor_samples") for speaker, value in samples.items()}

        fact = (origin.recording_receipt, programme_sound, samples)
        if by_source_frame.setdefault(origin.source_frame, fact) != fact:
            raise invalid("origin.source_frame")
        source = by_recording_receipt.setdefault(origin.recording_receipt, origin.source_frame)
        if source != origin.source_frame:
            raise invalid("origin.recording_receipt")
        frames.append(FrozenFrame(index, programme_sound, origin, samples))
    return FrozenEdition(edition, program, revision, roster, tuple(frames))


def decode_edition(raw):
    try:
        return _decode(raw)
    except Problem as error:
        raise Problem(400, "invalid_edition", field=error.payload["field"]) from error
