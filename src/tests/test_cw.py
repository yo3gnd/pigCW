import logging, unittest

from ..cw import (
    CW_INVALID,
    cw,
    cw_ascii,
    cwbits,
    get_ascii_from_cw,
    get_ascii_from_cw_raw,
    get_cw_from_ascii,
)


L = logging.getLogger(__name__)


TEXT_VECTORS = {
    "YO3GND": [0x1D, 0x0F, 0x38, 0x0B, 0x05, 0x09],
    "YO8YL": [0x1D, 0x0F, 0x27, 0x1D, 0x12],
    "YO3AX": [0x1D, 0x0F, 0x38, 0x06, 0x19],
    "PJ6Y": [0x16, 0x1E, 0x21, 0x1D],
    "Mama are mere? 123456789": [
        0x07, 0x06, 0x07, 0x06, 0x01, 0x06, 0x0A, 0x02,
        0x01, 0x07, 0x02, 0x0A, 0x02, 0x4C, 0x01, 0x3E,
        0x3C, 0x38, 0x30, 0x20, 0x21, 0x23, 0x27, 0x2F,
    ],
    "Bens best bent wire /K": [
        0x11, 0x02, 0x05, 0x08, 0x01, 0x11, 0x02, 0x08,
        0x03, 0x01, 0x11, 0x02, 0x05, 0x03, 0x01, 0x0E,
        0x04, 0x0A, 0x02, 0x01, 0x29, 0x0D,
    ],
    "TEST? /K, @HOME.": [
        0x03, 0x02, 0x08, 0x03, 0x4C, 0x01, 0x29, 0x0D,
        0x73, 0x01, 0x56, 0x10, 0x0F, 0x07, 0x02, 0x6A,
    ],
}

MAX_LEN_VECTORS = {
    "@": cwbits(0x16, 6),
    ".": cwbits(0x2A, 6),
    ",": cwbits(0x33, 6),
    "_": cwbits(0x2C, 6),
}

INVALID_ASCII = ["\n", "\t", "ă"]
INVALID_RAW = [0, 0x7F, 0xFF]
INVALID_BITS = [(-1, 1), (0, 7), (8, 3), (1, -1)]


def raw_from_bits(bits):
    return (1 << bits.len) | bits.data


class CWTests(unittest.TestCase):
    def assert_round_trip(self, text, expected_raw):
        L.debug("vector %s", text)

        got_raw = [cw(char) for char in text]
        self.assertEqual(got_raw, expected_raw)

        got_bits_raw = [raw_from_bits(get_cw_from_ascii(char)) for char in text]
        self.assertEqual(got_bits_raw, expected_raw)

        got_text_raw = "".join(get_ascii_from_cw_raw(raw) for raw in expected_raw)
        self.assertEqual(got_text_raw, text.lower())

        got_text_bits = "".join(
            get_ascii_from_cw(raw & ((1 << (raw.bit_length() - 1)) - 1), raw.bit_length() - 1)
            for raw in expected_raw
        )
        self.assertEqual(got_text_bits, text.lower())

    def test_vectors(self):
        for text, expected_raw in TEXT_VECTORS.items():
            with self.subTest(text=text):
                self.assert_round_trip(text, expected_raw)

    def test_max_len_symbols(self):
        for char, expected_bits in MAX_LEN_VECTORS.items():
            with self.subTest(char=char):
                L.debug("max len %s", char)
                bits = get_cw_from_ascii(char)
                self.assertEqual(bits, expected_bits)
                self.assertEqual(get_ascii_from_cw(bits.data, bits.len), char.lower())

    def test_space_and_case(self):
        L.debug("space and case")
        self.assertEqual(get_cw_from_ascii(" "), cwbits(0x00, 0))
        self.assertEqual(get_ascii_from_cw(0, 0), " ")
        self.assertEqual(get_cw_from_ascii("a"), get_cw_from_ascii("A"))

    def test_invalid_ascii(self):
        for char in INVALID_ASCII:
            with self.subTest(char=char):
                L.debug("bad ascii %r", char)
                with self.assertRaises(ValueError):
                    get_cw_from_ascii(char)

    def test_invalid_raw(self):
        for raw in INVALID_RAW:
            with self.subTest(raw=raw):
                L.debug("bad raw %#x", raw)
                with self.assertRaises(ValueError):
                    get_ascii_from_cw_raw(raw)

    def test_invalid_bits(self):
        for data, length in INVALID_BITS:
            with self.subTest(data=data, length=length):
                L.debug("bad bits data=%r len=%r", data, length)
                with self.assertRaises(ValueError):
                    get_ascii_from_cw(data, length)

    def test_full_table(self):
        for index in range(32, len(cw_ascii)):
            raw = cw_ascii[index]
            if raw == CW_INVALID:
                continue

            char = chr(index)
            expected_char = char.lower() if "A" <= char <= "Z" else char

            with self.subTest(char=char):
                bits = get_cw_from_ascii(char)
                self.assertEqual(raw_from_bits(bits), raw)
                self.assertEqual(get_ascii_from_cw_raw(raw), expected_char)
                self.assertEqual(get_ascii_from_cw(bits.data, bits.len), expected_char)

    def test_cw_logger(self):
        L.debug("cw logger")
        bits = get_cw_from_ascii("A")
        ch = get_ascii_from_cw(bits.data, bits.len)

        self.assertEqual(ch, "a")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
