import logging
from collections import namedtuple


L = logging.getLogger(__name__)


CW_INVALID = 0xFF
CW_MAX_LEN = 6


cwbits = namedtuple("cwbits", "data len")


cw_ascii = ([CW_INVALID] * 32) + [
    0x01, 0x75, 0x52, 0xFF, 0xFF, 0xFF, 0x22, 0x5E,  #  !"#$%&'
    0x2D, 0x6D, 0xFF, 0x2A, 0x73, 0x61, 0x6A, 0x29,  # ()*+,-./
    0x3F, 0x3E, 0x3C, 0x38, 0x30, 0x20, 0x21, 0x23,  # 01234567
    0x27, 0x2F, 0x47, 0x55, 0xFF, 0x31, 0xFF, 0x4C,  # 89:;<=>?
    0x56, 0x06, 0x11, 0x15, 0x09, 0x02, 0x14, 0x0B,  # @ABCDEFG
    0x10, 0x04, 0x1E, 0x0D, 0x12, 0x07, 0x05, 0x0F,  # HIJKLMNO
    0x16, 0x1B, 0x0A, 0x08, 0x03, 0x0C, 0x18, 0x0E,  # PQRSTUVW
    0x19, 0x1D, 0x13, 0xFF, 0xFF, 0xFF, 0xFF, 0x6C,  # XYZ[\]^_
    0xFF, 0x06, 0x11, 0x15, 0x09, 0x02, 0x14, 0x0B,  # `abcdefg
    0x10, 0x04, 0x1E, 0x0D, 0x12, 0x07, 0x05, 0x0F,  # hijklmno
    0x16, 0x1B, 0x0A, 0x08, 0x03, 0x0C, 0x18, 0x0E,  # pqrstuvw
    0x19, 0x1D, 0x13, 0xFF, 0xFF, 0xFF, 0xFF,        # xyz{|}~
]


def _normalize_ascii_char(char):
    if "A" <= char <= "Z":
        return char.lower()
    return char


def _build_reverse_lookup():
    return {
        raw: _normalize_ascii_char(chr(index))
        for index, raw in enumerate(cw_ascii[32:], start=32)
        if raw != CW_INVALID
    }


cw_raw_to_ascii = _build_reverse_lookup()


def _get_ascii_index(char):
    if not isinstance(char, str) or len(char) != 1:
        raise ValueError()

    index = ord(char)
    if index >= len(cw_ascii):
        raise ValueError()

    return index


def _lookup_cw_raw(char):
    raw = cw_ascii[_get_ascii_index(char)]
    if raw == CW_INVALID:
        raise ValueError()

    return raw


def _split_cw_raw(raw):
    if not isinstance(raw, int):
        raise ValueError()

    if raw <= 0:
        raise ValueError()

    length = raw.bit_length() - 1
    if length > CW_MAX_LEN:
        raise ValueError()

    data = raw & ((1 << length) - 1)
    return cwbits(data, length)


def _build_cw_raw(data, length):
    if data >= (1 << length): raise ValueError()
    return (1 << length) | data

def get_cw_from_ascii(char):
    raw = _lookup_cw_raw(char)
    bits = _split_cw_raw(raw)
    L.debug("cw ascii %r -> raw %#x -> %s", char, raw, bits)
    return bits

def get_ascii_from_cw_raw(raw):
    _split_cw_raw(raw)

    char = cw_raw_to_ascii.get(raw)
    if char is None: raise ValueError()

    L.debug("cw raw %#x -> ascii %r", raw, char)
    return char

def get_ascii_from_cw(data, length):
    return get_ascii_from_cw_raw(_build_cw_raw(data, length))

def cw(char):
    return _lookup_cw_raw(char)
