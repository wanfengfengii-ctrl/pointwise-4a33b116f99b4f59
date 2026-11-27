from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewFrame:
    frame: int
    sample: int
    origin: dict


def clamp_sample(value):
    return max(-127, min(127, value))


def render_program(frame, origin, samples):
    return PreviewFrame(frame, clamp_sample(sum(samples)), origin)
