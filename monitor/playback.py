from dataclasses import asdict

from monitor.install import read_installed_edition
from monitor.receipts import append_listen, receipt
from monitor.seats import read_operator
from rehearsal_contract import Problem, label, position


def listen_frame(db, data):
    seat = label(data.get("seat"), "seat")
    request = label(data.get("request"), "request")
    edition = position(data.get("edition"), "edition")
    frame_number = position(data.get("frame"), "frame")

    prior = receipt(db, seat, request)
    if prior is not None:
        if (prior.edition, prior.frame) != (edition, frame_number):
            raise Problem(409, "request_conflict", request=request)
        return asdict(prior)

    installed = read_installed_edition(db, seat, edition)
    if installed is None:
        raise Problem(404, "edition_unavailable", edition=edition)
    frame = installed.snapshot.frame_at(frame_number)
    if frame is None:
        raise Problem(404, "frame_unavailable", edition=edition, frame=frame_number)
    operator = read_operator(db, seat)
    if operator is None:
        raise Problem(409, "seat_unassigned", seat=seat)
    if operator.operator not in installed.snapshot.roster:
        raise Problem(409, "operator_not_in_roster", operator=operator.operator)

    sample = frame.monitor_samples[operator.operator]
    played = append_listen(db, seat, request, edition, frame_number, operator.operator,
                           sample, asdict(frame.origin))
    return asdict(played)
