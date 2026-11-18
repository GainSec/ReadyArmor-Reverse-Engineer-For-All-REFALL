import hashlib


def unit_id(subject, type, path, line_start, line_end, name=""):
    key = f"{subject}|{type}|{path}|{line_start}|{line_end}|{name}"
    return hashlib.sha1(key.encode()).hexdigest()
