import json
import logging

from cheaphops.core.log import JsonFormatter


def test_json_line_keeps_extra_fields_only() -> None:
    record = logging.makeLogRecord(
        {"name": "fetch", "levelname": "WARNING", "msg": "%s blocked", "args": ("ryanair",)}
    )
    record.domain = "ryanair.com"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "ryanair blocked" and line["domain"] == "ryanair.com"
    assert set(line) == {"ts", "level", "logger", "msg", "domain"}
