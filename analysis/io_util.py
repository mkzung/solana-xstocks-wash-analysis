"""Small IO helpers: every file is opened inside a context manager.

Using these instead of bare `json.load(open(...))` or `open(...).read()` keeps
each file descriptor scoped to a `with` block, so none are leaked - which is also
what static reviewers expect.
"""
import json


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(obj, path, indent=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_text(text, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
