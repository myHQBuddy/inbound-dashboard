# -*- coding: utf-8 -*-
"""Numbers whose MISSED calls are not counted on the Inbound Call Flow
dashboard.

These are myHQ trunk / dialler lines rather than customers. A missed call
from one of them is not a customer we failed to reach, so it should not
land in a missed-call metric or on the callback worklist.

Only missed rows are dropped. Answered calls from these lines stay, because
they represent conversations that did happen, and removing them would
quietly cut call volume as well.

Matched on the last ten digits: the same line appears as +9180682338xx,
9180682338xx and 80682338xx depending on the source.

This filter applies to data written from 2026-11-02 onward. Rows already in
inbound_call_records.csv are left as they are, so anything before that date
still carries its original classification.

Several entries below are not present in the data today; they are kept so
the list stays correct if those lines start appearing.
"""

EXCLUDED = {
    "2268493900",
    "8047482800",
    "8067947080",
    "8068233800",
    "8068233802",
    "8068233803",
    "8068233804",
    "8068233813",
    "8068233815",
    "8068233817",
    "8068233819",
    "8068233820",
    "8068233830",
    "8069809587",
    "8071365430",
}


def _last10(number):
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def is_trunk(number):
    """True when this number is a trunk line rather than a customer."""
    return _last10(number) in EXCLUDED


def drop_from_missed(number, status):
    """True when this row is a missed call from a trunk line.

    Answered rows return False and are kept.
    """
    return status != "answered" and is_trunk(number)
