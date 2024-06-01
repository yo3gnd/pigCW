import sys, os, re, random

class CWSign():
    def __init__():
        pass

# class DIT(CWSign):
#    def __init__(): pass
#class DAH(CWSign):
#    def __init__(): pass
# class LETTER_SPACE(CWSign):
#    def __init__(): pass
# class WORD_SPACE(CWSign):
#    def __init__(): pass
DIT=object()
DAH=object()
LETTER_SPACE=object()
WORD_SPACE=object()

CW_INVALID = 0xFF

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

def cw(c):
    a = ord(c)
    if a >= len(cw_ascii):
        return CW_INVALID

    return cw_ascii[a]

if False:
    MORSE_TABLE = {
        'a': (DIT, DAH),
        'b': (DAH, DIT, DIT, DIT),
        'c': (DAH, DIT, DAH, DIT),
        'd': (DAH, DIT, DIT),
        'e': (DIT, ),
        'f': (DIT, DIT, DAH, DIT),
        'g': (DAH, DAH, DIT),
        'h': (DIT, DIT, DIT, DIT),
        'i': (DIT, DIT),
        'j': (DIT, DAH, DAH, DAH),

        'k': (DAH, DIT, DAH),
        'l': (DIT, DAH, DIT, DIT),
        'm': (DAH, DAH),
        'n': (DAH, DIT),
        'o': (DAH, DAH, DAH),
        'p': (DIT, DAH, DAH, DIT),
        'q': (DAH, DAH, DIT, DAH),
        'r': (DIT, DAH, DIT),
        's': (DIT, DIT, DIT),
        't': (DAH, ),
        'u': (DIT, DIT, DAH),
        'v': (DIT, DIT, DIT, DAH),
        'w': (DIT, DAH, DAH),
        'x': (DAH, DIT, DIT, DAH),
        'y': (DAH, DIT, DAH, DAH),
        'z': (DAH, DAH, DIT, DIT),
        '0': (DAH, DAH, DAH, DAH, DAH),
        '1': (DIT, DAH, DAH, DAH, DAH),
        '2': (DIT, DIT, DAH, DAH, DAH),
        '3': (DIT, DIT, DIT, DAH, DAH),
        '4': (DIT, DIT, DIT, DIT, DAH),
        '5': (DIT, DIT, DIT, DIT, DIT),
        '6': (DAH, DIT, DIT, DIT, DIT),
        '7': (DAH, DAH, DIT, DIT, DIT),
        '8': (DAH, DAH, DAH, DIT, DIT),
        '9': (DAH, DAH, DAH, DAH, DIT),
        '.': (DIT, DAH, DIT, DAH, DIT, DAH),
        ',': (DAH, DAH, DIT, DIT, DAH, DAH),
        '/': (DAH, DIT, DIT, DAH, DIT),
        '?': (DIT, DIT, DAH, DAH, DIT, DIT),
        '=': (DAH, DIT, DIT, DIT, DAH),
        "'": (DIT, DAH, DAH, DAH, DAH, DIT),
        '!': (DAH, DIT, DAH, DIT, DAH, DAH),
        '(': (DAH, DIT, DAH, DAH, DIT),
        ')': (DAH, DIT, DAH, DAH, DIT, DAH),
        '&': (DIT, DAH, DIT, DIT, DIT),
        ':': (DAH, DAH, DAH, DIT, DIT, DIT),
        ';': (DAH, DIT, DAH, DIT, DAH, DIT),
        '+': (DIT, DAH, DIT, DAH, DIT),
        '-': (DAH, DIT, DIT, DIT, DIT, DAH),
        '_': (DIT, DIT, DAH, DAH, DIT, DAH),
        '"': (DIT, DAH, DIT, DIT, DAH, DIT),
        '$': (DIT, DIT, DIT, DAH, DIT, DIT, DAH),
    }

class CWDecoder():
    def __init__(self):
        d = self.generate_timings("TEST MAMA ARE MERE")
        d = self.generate_timings("YO3GND YO8YLX")
        self.analyze_timings(d)
    
    def get_cw(self, char_):
        return cw(char_)

    def get_cwr(self, char_):
        d = self.get_cw(char_)
        if d == CW_INVALID:
            return
        while d > 1:
            if d & 1:
                print(DAH)
            else:
                print(DIT)
            d = d >> 1

    def get_cw_message(self, msg):
        result = []
        for letter in msg:
            d = self.get_cw(letter)
            if d == CW_INVALID:
                continue
            if d == 0x01:
                result.append(WORD_SPACE)
                continue
            while d > 1:
                if d & 1:
                    result.append(DAH)
                else:
                    result.append(DIT)
                d = d >> 1
            result.append(LETTER_SPACE)
        return result

    def generate_timings(self, msg):
        symbols_ = self.get_cw_message(msg)
        ms_dit = 60
        ms_dah = 180
        ms_symbol = ms_dit
        ms_letter = ms_dit * -3
        ms_word = ms_dit * -7

        durs = {DIT: ms_dit, DAH: ms_dah, LETTER_SPACE: ms_letter, WORD_SPACE: ms_word}
        result = []
        for symbol in symbols_:
            d = durs[symbol] * 1.0
            # print(d)
            m = random.randrange(950, 1050)
            m = m / 1000.0
            d*= m
            d = round(d)
            result.append(d)

        return result

    def analyze_timings(self, timings):
        frequency = dict()
        timings_abs = [abs(x) for x in timings]
        timings_plus = [x for x in timings if x > 0]
        for t in timings:
            z = abs(t)
            if z in frequency:
                frequency[z] += 1
            else:
                frequency[z] = 1
        xavg = sum(timings_plus) / len(timings_plus)

        def cluster(items, key_func):
            items = sorted(items)
            clusters = [[items[0]]]
            for item in items[1:]:
                cluster = clusters[-1]
                last_item = cluster[-1]
                if abs(item-last_item) < xavg*0.8:
                    cluster.append(item)
                else:
                    clusters.append([item])
            return clusters

        res = cluster(timings_plus, xavg)
        avg1 = round(sum(res[0]) / len(res[0]))
        avg2 = round(sum(res[1]) / len(res[1]))
        # print(res, avg1, avg2)


        ms_dit = min(avg1, avg2)
        ms_dah = max(avg1, avg2)

        r = ""
        print(timings)
        aw = 0.1 # allowed timing variance
        for i in timings:
            if i > 0:
                if ms_dit * 0.9 < i < ms_dit * 1.1:
                    r += "."
                if ms_dah * 0.9 < i < ms_dah * 1.1:
                    r += "-"
            else:
                if ms_dit * 7 * (1.0 - aw) < abs(i) < ms_dit * 7 * (1.0 + aw):
                    r += " /  "
                if ms_dit * 3 * (1.0 - aw) < abs(i) < ms_dit * 3 * (1.0 + aw):
                    r += " "
        print(r)
            
