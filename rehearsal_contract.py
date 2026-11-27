class Problem(Exception):
    def __init__(self, status, error, **details):
        super().__init__(error)
        self.status = status
        self.payload = {"error": error, **details}


def invalid(field):
    return Problem(400, "invalid_input", field=field)


def label(value, field):
    if type(value) is not str or not 1 <= len(value) <= 120:
        raise invalid(field)
    if not value.isprintable() or value != value.strip():
        raise invalid(field)
    return value


def position(value, field):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise invalid(field)
    return value


def query_position(data, field):
    value = data.get(field)
    if value is None or len(value) > 19 or not value.isascii() or not value.isdecimal():
        raise invalid(field)
    return position(int(value), field)


def object_value(value, field):
    if type(value) is not dict:
        raise invalid(field)
    return value


def array_value(value, field):
    if type(value) is not list:
        raise invalid(field)
    return value
