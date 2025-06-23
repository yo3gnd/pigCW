import time

from .cw import get_ascii_from_cw_raw, get_cw_from_ascii, cw_raw_to_ascii


def encode_cw_byte(character):
    try:
        z = get_cw_from_ascii(character)
    except ValueError:
        return None

    cw_byte = (1 << z.len) | z.data

    if cw_byte <= 1:
        return None
    return cw_byte


class KeyerState:
    def __init__(self):
        self.straight_down = False
        self.straight_until = 0


        self.dit_down = False
        self.dah_down = False


        self.sending = "idle"
        self.sending_end_ms = 0
        self.space_end_ms = 0

        self.sending_kind = None

        self.mem_dit = False
        self.mem_dah = False


        self.last_repeat = None
        self.ka_q = []

        self.tx_begin_ms = 0

        self.tx_begin_tick = 0

        self.cw_byte = 1
        self.cw_t = 0

        self.cw_word = ""
        self.cw_word_t = 0


class KeyerEngine:
    def __init__(self, c, out, cb, gpio):
        self.c = c
        self.out = out
        self.cb = cb
        self.gpio = gpio

        self.base_ms = round(time.time() * 1000)
        self.s = KeyerState()

    def set_mem(self, kind):
        s = self.s

        if self.c.keyer_mode == "a":
            label = "mode a mem"
        elif self.c.keyer_mode == "b":
            label = "mode b mem"
        else:
            label = "mem"

        if kind == "dit":
            if not s.mem_dit:
                print(label, "dit")

            s.mem_dit = True
            return

        if not s.mem_dah:
            print(label, "dah")

        s.mem_dah = True

    def pop_mem(self):
        s = self.s

        if s.mem_dit and s.mem_dah:
            if s.last_repeat == "dit":
                s.mem_dah = False
                return "dah"

            s.mem_dit = False
            return "dit"

        if s.mem_dit:
            s.mem_dit = False
            return "dit"

        if s.mem_dah:
            s.mem_dah = False
            return "dah"

        return None

    def clear_tx(self):
        s = self.s

        s.sending = "idle"
        s.sending_end_ms = 0

        s.space_end_ms = 0
        s.sending_kind = None
        s.mem_dit = False

        s.mem_dah = False
        s.last_repeat = None
        s.ka_q = []


        s.tx_begin_ms = 0
        s.tx_begin_tick = 0
        s.cw_byte = 1

        s.cw_t = 0
        s.cw_word = ""
        s.cw_word_t = 0

        self.out.set_enabled(False)

    def cw_add(self, kind):
        s = self.s

        s.cw_t = 0
        s.cw_byte = s.cw_byte << 1

        if kind == "dah":
            s.cw_byte |= 1

        print("cw bits", hex(s.cw_byte))

    def cw_dec(self):
        s = self.s

        if s.cw_byte <= 1:
            return None

        try:
            ch = get_ascii_from_cw_raw(s.cw_byte)
        except ValueError:
            ch = "?"

        print("cw char", ch)
        s.cw_byte = 1

        s.cw_t = 0
        s.cw_word += ch
        s.cw_word_t = round(time.time() * 1000) + (self.c.dit_ms * 4)

        return ch

    def cw_word_dec(self):
        s = self.s

        if not s.cw_word:
            s.cw_word_t = 0
            return

        print("cw word", s.cw_word)
        s.cw_word = ""
        s.cw_word_t = 0

    def next_kind(self):
        s = self.s

        if self.c.keyer_mode == "keyahead":
            if s.ka_q:
                kind = s.ka_q.pop(0)
                print("ka pop", kind)
                return kind

            if s.dit_down and s.dah_down:
                if s.last_repeat:
                    return s.last_repeat
                return "dit"

            if s.dit_down:
                return "dit"
            if s.dah_down:
                return "dah"

            return None

        kind = self.pop_mem()
        if kind:
            return kind

        if s.dit_down and s.dah_down:
            if s.last_repeat == "dit":
                return "dah"
            if s.last_repeat == "dah":
                return "dit"
            return "dit"

        if s.dit_down:
            return "dit"
        if s.dah_down:
            return "dah"

        return None

    def start_tx(self, kind, now_ms, gpio_tick):
        s = self.s

        s.sending = "tone"
        s.sending_kind = kind
        s.tx_begin_ms = now_ms

        s.tx_begin_tick = gpio_tick
        s.last_repeat = kind

        self.cw_add(kind)
        self.out.set_frequency(self.c.tx_tone_hz)

        self.out.set_enabled(True)

        if kind == "dit":
            print("tx start dit", gpio_tick, self.c.dit_ms)
            s.sending_end_ms = now_ms + self.c.dit_ms
            if self.c.keyer_mode == "b" and s.dah_down:
                self.set_mem("dah")
            return

        print("tx start dah", gpio_tick, self.c.dah_ms)
        s.sending_end_ms = now_ms + self.c.dah_ms
        if self.c.keyer_mode == "b" and s.dit_down:
            self.set_mem("dit")

    def end_tx(self, now_ms):
        s = self.s

        dur_ms = now_ms - s.tx_begin_ms
        if dur_ms < 1:
            dur_ms = 1

        self.out.set_enabled(False)
        print("tx stop", s.tx_begin_tick, now_ms)

        if s.sending_kind == "dit":
            self.cb(0, s.tx_begin_ms - self.base_ms, dur_ms)
        else:
            self.cb(1, s.tx_begin_ms - self.base_ms, dur_ms)

        s.tx_begin_ms = 0
        s.tx_begin_tick = 0

        s.sending = "space"
        s.space_end_ms = now_ms + self.c.element_space_ms

    def timer_ev(self):
        s = self.s
        now_ms = round(time.time() * 1000)

        if s.straight_down:
            return

        if s.sending == "idle" and s.cw_t and now_ms >= s.cw_t:
            self.cw_dec()
            return

        if s.sending == "idle" and s.cw_word_t and now_ms >= s.cw_word_t:
            self.cw_word_dec()
            return

        if s.sending == "tone" and now_ms >= s.sending_end_ms:
            self.end_tx(now_ms)
            return

        if s.sending == "space" and now_ms >= s.space_end_ms:
            s.sending = "idle"
            s.space_end_ms = 0

            s.sending_kind = None

            k = self.next_kind()
            if k:
                self.start_tx(k, now_ms, self.gpio.get_current_tick())
            elif s.cw_byte > 1:
                s.cw_t = now_ms + (self.c.dit_ms * 2)

    def wait_s(self):
        s = self.s
        now_ms = round(time.time() * 1000)

        if s.sending == "tone":
            x = (s.sending_end_ms - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        if s.sending == "space":
            x = (s.space_end_ms - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        if s.cw_t:
            x = (s.cw_t - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        if s.cw_word_t:
            x = (s.cw_word_t - now_ms) / 1000.0
            if x < 0:
                return 0
            return x

        return 0.2

    def straight_ev(self, pressed, gpio_tick, now_ms):
        s = self.s

        if pressed:
            s.straight_down = True
            s.straight_until = 0
            print("straight down", gpio_tick)

            self.clear_tx()
            s.straight_down = True
            s.dit_down = False

            s.dah_down = False
            s.tx_begin_ms = now_ms
            s.tx_begin_tick = gpio_tick

            self.out.set_frequency(self.c.tx_tone_hz)
            self.out.set_enabled(True)
            return

        print("straight up", gpio_tick)

        if s.tx_begin_ms:
            dur_ms = now_ms - s.tx_begin_ms
            if dur_ms < 1:
                dur_ms = 1
            self.cb(0, s.tx_begin_ms - self.base_ms, dur_ms)

        self.out.set_enabled(False)
        s.tx_begin_ms = 0
        s.tx_begin_tick = 0

        s.straight_down = False
        s.straight_until = now_ms + self.c.straight_disable_ms
        print("straight inhibit", s.straight_until)

    def paddle_ev(self, kind, pressed, gpio_tick, now_ms):
        s = self.s

        if pressed and s.cw_t:
            if now_ms >= s.cw_t:
                self.cw_dec()
            else:
                s.cw_t = 0

        if pressed and s.cw_word_t:
            if now_ms >= s.cw_word_t:
                self.cw_word_dec()
            else:
                s.cw_word_t = 0

        if self.c.reverse_paddles:
            if kind == "dit":
                kind = "dah"
            else:
                kind = "dit"

        if s.straight_down:
            print("ignore paddle, straight down")
            return

        if now_ms < s.straight_until:
            print("ignore paddle, inhibit")
            return

        if kind == "dit":
            was = s.dit_down
            s.dit_down = bool(pressed)
        else:
            was = s.dah_down

            s.dah_down = bool(pressed)

        if not pressed:
            return

        if kind == "dit":
            print("dit down", gpio_tick)
        else:
            print("dah down", gpio_tick)

        if self.c.keyer_mode == "keyahead":
            s.ka_q.append(kind)
            print("ka push", kind)
        elif s.sending and s.sending_kind and kind != s.sending_kind:
            if self.c.keyer_mode == "a":
                if not was:
                    self.set_mem(kind)
            elif self.c.keyer_mode == "b":
                self.set_mem(kind)

        if s.sending == "idle":
            k = self.next_kind()
            if k:
                self.start_tx(k, now_ms, gpio_tick)
