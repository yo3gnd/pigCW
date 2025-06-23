from collections import namedtuple


CW_INVALID = 0xFF
CW_MAX_LEN = 6
cwbits = namedtuple("cwbits", "data len")

cw_ascii = ([CW_INVALID] * 32) + [
    0x01, 0x75, 0x52, 0xFF, 0xFF, 0xFF, 0x22, 0x5E, #  !"#$%&'
    0x2D, 0x6D, 0xFF, 0x2A, 0x73, 0x61, 0x6A, 0x29, # ()*+,-./
    0x3F, 0x3E, 0x3C, 0x38, 0x30, 0x20, 0x21, 0x23, # 01234567
    0x27, 0x2F, 0x47, 0x55, 0xFF, 0x31, 0xFF, 0x4C, # 89:;<=>?
    0x56, 0x06, 0x11, 0x15, 0x09, 0x02, 0x14, 0x0B, # @ABCDEFG
    0x10, 0x04, 0x1E, 0x0D, 0x12, 0x07, 0x05, 0x0F, # HIJKLMNO
    0x16, 0x1B, 0x0A, 0x08, 0x03, 0x0C, 0x18, 0x0E, # PQRSTUVW
    0x19, 0x1D, 0x13, 0xFF, 0xFF, 0xFF, 0xFF, 0x6C, # XYZ[\\]^_

    0xFF, 0x06, 0x11, 0x15, 0x09, 0x02, 0x14, 0x0B, # `abcdefg
    0x10, 0x04, 0x1E, 0x0D, 0x12, 0x07, 0x05, 0x0F, # hijklmno
    0x16, 0x1B, 0x0A, 0x08, 0x03, 0x0C, 0x18, 0x0E, # pqrstuvw
    0x19, 0x1D, 0x13, 0xFF, 0xFF, 0xFF, 0xFF,       # xyz{|}~
]


cw_raw_to_ascii = {}
for i in range(32, len(cw_ascii)):
    z = cw_ascii[i]
    if z == CW_INVALID:
        continue

    c = chr(i)
    if "A" <= c <= "Z":
        c = c.lower()

    cw_raw_to_ascii[z] = c




def _get_ascii_idx(char):
    if not isinstance(char, str) or len(char) != 1:
        raise ValueError()

    a = ord(char)
    if a >= len(cw_ascii):
        raise ValueError()

    return a


def _lookup_cw_raw(char):
    a = _get_ascii_idx(char)
    raw = cw_ascii[a]

    if raw == CW_INVALID:
        raise ValueError()

    return raw


def _split_cw_raw(raw):
    if not isinstance(raw, int):
        raise ValueError()

    if raw <= 0:
        raise ValueError()

    n = raw.bit_length() - 1
    if n > CW_MAX_LEN:
        raise ValueError()

    d = raw & ((1 << n) - 1)

    return cwbits(d, n)


def get_cw_from_ascii(char):
    raw = _lookup_cw_raw(char)
    return _split_cw_raw(raw)

def get_ascii_from_cw_raw(raw):
    _split_cw_raw(raw)

    char = cw_raw_to_ascii.get(raw)
    if char is None: raise ValueError()

    return char

def get_ascii_from_cw(data, length):
    return get_ascii_from_cw_raw(_build_cw_raw(data, length))

def cw(char):
    return _lookup_cw_raw(char)


def run_tests():
    def raw_from_bits(bits):
        return (1 << bits.len) | bits.data

    def fmt_raw_list(items):
        return "[" + ", ".join(hex(x) for x in items) + "]"

    def assert_eq(got, exp, label):
        if got != exp:
            raise AssertionError(f"{label}: got {got!r}, expected {exp!r}")

    vectors = {
        "YO3GND": [0x1D, 0x0F, 0x38, 0x0B, 0x05, 0x09],
        "YO8YL": [0x1D, 0x0F, 0x27, 0x1D, 0x12],
        "YO3AX": [0x1D, 0x0F, 0x38, 0x06, 0x19],
        "PJ6Y": [0x16, 0x1E, 0x21, 0x1D],
        "Mama are mere? 123456789": [ 0x07, 0x06, 0x07, 0x06, 0x01, 0x06, 0x0A, 0x02, 0x01, 0x07, 0x02, 0x0A, 0x02, 0x4C, 0x01, 0x3E, 0x3C, 0x38, 0x30, 0x20, 0x21, 0x23, 0x27, 0x2F, ],
        "Bens best bent wire /K": [ 0x11, 0x02, 0x05, 0x08, 0x01, 0x11, 0x02, 0x08, 0x03, 0x01, 0x11, 0x02, 0x05, 0x03, 0x01, 0x0E, 0x04, 0x0A, 0x02, 0x01, 0x29, 0x0D, ],
    }

    for text, exp_raw in vectors.items():
        got_raw = [cw(ch) for ch in text]
        assert_eq(got_raw, exp_raw, text + " raw")

        got_bits_raw = [raw_from_bits(get_cw_from_ascii(ch)) for ch in text]
        assert_eq(got_bits_raw, exp_raw, text + " bits")

        got_text_raw = "".join(get_ascii_from_cw_raw(x) for x in exp_raw)
        assert_eq(got_text_raw, text.lower(), text + " raw rev")

        got_text_bits = "".join(
            get_ascii_from_cw(x & ((1 << (x.bit_length() - 1)) - 1), x.bit_length() - 1)
            for x in exp_raw
        )
        assert_eq(got_text_bits, text.lower(), text + " bits rev")

    vectors = {
        "TEST? /K, @HOME.": [
            0x03, 0x02, 0x08, 0x03, 0x4C, 0x01, 0x29, 0x0D,
            0x73, 0x01, 0x56, 0x10, 0x0F, 0x07, 0x02, 0x6A,
        ],
    }

    for text, exp_raw in vectors.items():
        got_raw = [cw(ch) for ch in text]
        assert_eq(got_raw, exp_raw, text + " raw")

        got_text = "".join(get_ascii_from_cw_raw(x) for x in exp_raw)
        assert_eq(got_text, text.lower(), text + " rev")

        print("ok more", text, fmt_raw_list(exp_raw))

    max_len = {
        "@": cwbits(0x16, 6),
        ".": cwbits(0x2A, 6),
        ",": cwbits(0x33, 6),
        "_": cwbits(0x2C, 6),
    }

    for ch, exp in max_len.items():
        got = get_cw_from_ascii(ch)
        assert_eq(got, exp, ch + " max")
        assert_eq(get_ascii_from_cw(exp.data, exp.len), ch.lower(), ch + " max rev")

    z = get_cw_from_ascii(" ")
    assert_eq(z, cwbits(0x00, 0), "space bits")
    assert_eq(get_ascii_from_cw(0, 0), " ", "space rev")

    a = get_cw_from_ascii("a")
    b = get_cw_from_ascii("A")
    assert_eq(a, b, "case fold a")

    bad_ascii = ["\n", "\t", "ă"]
    for ch in bad_ascii:
        try:
            get_cw_from_ascii(ch)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad ascii accepted: {ch!r}")

    bad_raw = [0, 0x7F, 0xFF]
    for raw in bad_raw:
        try:
            get_ascii_from_cw_raw(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad raw accepted: {raw!r}")

    bad_bits = [
        (-1, 1),
        (0, 7),
        (8, 3),
        (1, -1),
    ]
    for data, length in bad_bits:
        try:
            get_ascii_from_cw(data, length)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad bits accepted: {(data, length)!r}")

    for i in range(32, len(cw_ascii)):
        raw = cw_ascii[i]
        if raw == CW_INVALID:
            continue

        ch = chr(i)
        exp = ch
        if "A" <= exp <= "Z":
            exp = exp.lower()

        bits = get_cw_from_ascii(ch)
        assert_eq(raw_from_bits(bits), raw, ch + " table raw")
        assert_eq(get_ascii_from_cw_raw(raw), exp, ch + " table raw rev")
        assert_eq(get_ascii_from_cw(bits.data, bits.len), exp, ch + " table bits rev")

    print("more tests ok")


if __name__ == "__main__":
    run_tests()
