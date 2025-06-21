#!/usr/bin/env python
import pigpio, json, os, sys, time, queue, threading
from websocket import create_connection, WebSocketTimeoutException, WebSocketConnectionClosedException
from experiments.cwd import cw, CW_INVALID
from .cfg import Cfg

pi = pigpio.pi()

running = False
straight_down = 0
straight_until = 0
dit_down = 0
dah_down = 0
sending = 0
sending_end_tick = 0
space_end_tick = 0
sending_kind = None
mem_dit = 0
mem_dah = 0
last_repeat = None
ka_q = []
tx_begin_ms = 0
tx_begin_tick = 0

class KeyReader():
    def __init__(self, c, cb):

            self.cb = cb
            self.c = c
            self.q = queue.Queue()
            self.btx = Buzzer(c.tx_tone, c.GPIO_BUZZER_TX)
            self.base_ms = round(time.time() * 1000)
            self.cw_byte = 1
            self.cw_t = 0
            self.cw_word = ""
            self.cw_word_t = 0
            self.gpio_dit = c.GPIO_DIT
            self.gpio_dah = c.GPIO_DAH
            self.gpio_straight = c.GPIO_STRAIGHT
            pi.set_pull_up_down(self.gpio_dit, pigpio.PUD_UP)
            pi.set_glitch_filter(self.gpio_dit, c.glitch_filter_dit)
            pi.set_pull_up_down(self.gpio_dah, pigpio.PUD_UP)
            pi.set_glitch_filter(self.gpio_dah, c.glitch_filter_dah)
            pi.set_pull_up_down(self.gpio_straight, pigpio.PUD_UP)
            pi.set_glitch_filter(self.gpio_straight, c.glitch_filter_straight)

            def cbf_dit(gpio, level, tick):
                self.cbf("dit", level, tick)

            def cbf_dah(gpio, level, tick):
                self.cbf("dah", level, tick)

            def cbf_straight(gpio, level, tick):
                self.cbf("straight", level, tick)

            self.cb_dit = pi.callback(self.gpio_dit, pigpio.EITHER_EDGE, cbf_dit)
            self.cb_dah = pi.callback(self.gpio_dah, pigpio.EITHER_EDGE, cbf_dah)
            self.cb_straight = pi.callback(self.gpio_straight, pigpio.EITHER_EDGE, cbf_straight)

            self.start_loop()

    def __del__(self):
        pass
        # self.cb_dit.cancel()
        # self.cb_dah.cancel()
        # self.cb_straight.cancel()

    def start_loop(self):
        self.run = True
        threading.Thread(target=self.key_thread, daemon=False).start()
        
    def stop_loop(self):
        self.run = False

    def cbf(self, kind, level, tick):
       obj = (kind, not level, tick)
       self.q.put(obj)

    def set_mem(self, kind):
        global mem_dit, mem_dah
        if self.c.mode == "a":
            s = "mode a mem"
        elif self.c.mode == "b":
            s = "mode b mem"
        else:
            s = "mem"
        if kind == "dit":
            if not mem_dit:
                print(s, "dit")
            mem_dit = 1
        else:
            if not mem_dah:
                print(s, "dah")
            mem_dah = 1

    def pop_mem(self):
        global mem_dit, mem_dah, last_repeat
        if mem_dit and mem_dah:
            if last_repeat == "dit":
                mem_dah = 0
                return "dah"
            mem_dit = 0
            return "dit"
        if mem_dit:
            mem_dit = 0
            return "dit"
        if mem_dah:
            mem_dah = 0
            return "dah"
        return None

    def clear_tx(self):
        global sending, sending_end_tick, space_end_tick, sending_kind
        global mem_dit, mem_dah, last_repeat, ka_q, tx_begin_ms, tx_begin_tick
        sending = 0
        sending_end_tick = 0
        space_end_tick = 0
        sending_kind = None
        mem_dit = 0
        mem_dah = 0
        last_repeat = None
        ka_q = []
        tx_begin_ms = 0
        tx_begin_tick = 0
        self.cw_byte = 1
        self.cw_t = 0
        self.cw_word = ""
        self.cw_word_t = 0
        self.btx.buzz(0)

    def cw_add(self, kind):
        self.cw_t = 0
        self.cw_byte = self.cw_byte << 1
        if kind == "dah":
            self.cw_byte |= 1
        print("cw bits", hex(self.cw_byte))

    def cw_cmp(self, ch):
        d = cw(ch)
        if d == CW_INVALID:
            return CW_INVALID
        x = 1
        while d > 1:
            x = x << 1
            if d & 1:
                x |= 1
            d = d >> 1
        return x

    def cw_dec(self):
        d = self.cw_byte
        if d <= 1:
            return
        for i in range(32, 127):
            ch = chr(i)
            if self.cw_cmp(ch) != d:
                continue
            if "A" <= ch <= "Z":
                ch = ch.lower()
            print("cw char", ch)
            self.cw_byte = 1
            self.cw_t = 0
            self.cw_word += ch
            self.cw_word_t = round(time.time() * 1000) + (self.c.dit_ms * 4)
            return ch
        print("cw char", "?")
        self.cw_byte = 1
        self.cw_t = 0
        self.cw_word += "?"
        self.cw_word_t = round(time.time() * 1000) + (self.c.dit_ms * 4)

    def cw_word_dec(self):
        if not self.cw_word:
            self.cw_word_t = 0
            return
        print("cw word", self.cw_word)
        self.cw_word = ""
        self.cw_word_t = 0

    def next_kind(self):
        global dit_down, dah_down, last_repeat, ka_q
        if self.c.mode == "keyahead":
            if ka_q:
                x = ka_q.pop(0)
                print("ka pop", x)
                return x
            if dit_down and dah_down:
                if last_repeat:
                    return last_repeat
                return "dit"
            if dit_down:
                return "dit"
            if dah_down:
                return "dah"
            return None
        x = self.pop_mem()
        if x:
            return x
        if dit_down and dah_down:
            if last_repeat == "dit":
                return "dah"
            if last_repeat == "dah":
                return "dit"
            return "dit"
        if dit_down:
            return "dit"
        if dah_down:
            return "dah"
        return None

    def begin_tx(self, kind, now, tick):
        global sending, sending_kind, sending_end_tick, tx_begin_ms, tx_begin_tick
        global last_repeat, dah_down, dit_down
        sending = 1
        sending_kind = kind
        tx_begin_ms = now
        tx_begin_tick = tick
        last_repeat = kind
        self.cw_add(kind)
        self.btx.change_freq(self.c.tx_tone)
        self.btx.buzz(1)
        if kind == "dit":
            print("tx start dit", tick, self.c.dit_ms)
            sending_end_tick = now + self.c.dit_ms
            if self.c.mode == "b" and dah_down:
                self.set_mem("dah")
        else:
            print("tx start dah", tick, self.c.dah_ms)
            sending_end_tick = now + self.c.dah_ms
            if self.c.mode == "b" and dit_down:
                self.set_mem("dit")

    def end_tx(self, now):
        global sending, space_end_tick, tx_begin_ms, sending_kind
        dur = now - tx_begin_ms
        if dur < 1:
            dur = 1
        self.btx.buzz(0)
        print("tx stop", now)
        if sending_kind == "dit":
            self.cb(0, tx_begin_ms - self.base_ms, dur)
        else:
            self.cb(1, tx_begin_ms - self.base_ms, dur)
        tx_begin_ms = 0
        sending = 2
        space_end_tick = now + self.c.elem_space

    def handle_deadline(self):
        global sending, sending_kind, space_end_tick
        now = round(time.time() * 1000)
        if straight_down:
            return
        if not sending and self.cw_t and now >= self.cw_t:
            self.cw_dec()
            return
        if not sending and self.cw_word_t and now >= self.cw_word_t:
            self.cw_word_dec()
            return
        if sending == 1 and now >= sending_end_tick:
            self.end_tx(now)
            return
        if sending == 2 and now >= space_end_tick:
            sending = 0
            space_end_tick = 0
            sending_kind = None
            k = self.next_kind()
            if k:
                self.begin_tx(k, now, pi.get_current_tick())
            elif self.cw_byte > 1:
                self.cw_t = now + (self.c.dit_ms * 2)

    def event_wait(self):
        now = round(time.time() * 1000)
        if sending == 1:
            x = (sending_end_tick - now) / 1000.0
            if x < 0:
                return 0
            return x
        if sending == 2:
            x = (space_end_tick - now) / 1000.0
            if x < 0:
                return 0
            return x
        if self.cw_t:
            x = (self.cw_t - now) / 1000.0
            if x < 0:
                return 0
            return x
        if self.cw_word_t:
            x = (self.cw_word_t - now) / 1000.0
            if x < 0:
                return 0
            return x
        return 0.2

    def handle_straight(self, pressed, tick, now):
        global straight_down, straight_until, dit_down, dah_down, tx_begin_ms
        if pressed:
            straight_down = 1
            straight_until = 0
            print("straight down", tick)
            self.clear_tx()
            dit_down = 0
            dah_down = 0
            tx_begin_ms = now
            self.btx.change_freq(self.c.tx_tone)
            self.btx.buzz(1)
        else:
            print("straight up", tick)
            if tx_begin_ms:
                dur = now - tx_begin_ms
                if dur < 1:
                    dur = 1
                self.cb(0, tx_begin_ms - self.base_ms, dur)
            self.btx.buzz(0)
            tx_begin_ms = 0
            straight_down = 0
            straight_until = now + self.c.straight_ms
            print("straight inhibit", straight_until)

    def handle_paddle(self, kind, pressed, tick, now):
        global dit_down, dah_down, ka_q
        if pressed and self.cw_t:
            if now >= self.cw_t:
                self.cw_dec()
            else:
                self.cw_t = 0
        if pressed and self.cw_word_t:
            if now >= self.cw_word_t:
                self.cw_word_dec()
            else:
                self.cw_word_t = 0
        if self.c.reverse:
            if kind == "dit":
                kind = "dah"
            else:
                kind = "dit"

        if straight_down:
            print("ignore paddle, straight down")
            return

        if now < straight_until:
            print("ignore paddle, inhibit")
            return

        if kind == "dit":
            was = dit_down
            dit_down = 1 if pressed else 0
        else:
            was = dah_down
            dah_down = 1 if pressed else 0

        if pressed:
            if kind == "dit":
                print("dit down", tick)
            else:
                print("dah down", tick)

            if self.c.mode == "keyahead":
                ka_q.append(kind)
                print("ka push", kind)
            elif sending and sending_kind and kind != sending_kind:
                if self.c.mode == "a":
                    if not was:
                        self.set_mem(kind)
                elif self.c.mode == "b":
                    self.set_mem(kind)

            if not sending:
                k = self.next_kind()
                if k:
                    self.begin_tx(k, now, tick)

    def key_thread(self):
        while self.run:
            try:
                nx = self.q.get(timeout=self.event_wait())
            except queue.Empty:
                self.handle_deadline()
                continue
            kind = nx[0]
            pressed = nx[1]
            tick = nx[2]
            now = round(time.time() * 1000)
            if kind == "straight":
                self.handle_straight(pressed, tick, now)
                self.q.task_done()
                self.handle_deadline()
                continue
            self.handle_paddle(kind, pressed, tick, now)
            self.q.task_done()
            self.handle_deadline()

class Buzzer():
    def __init__(self, freq, pin):
        self.pin = pin
        pi.set_mode(self.pin, pigpio.OUTPUT)
        pi.set_PWM_range(self.pin, 100)
        self.change_freq(freq)

    def change_freq(self, freq):
        self.freq = int(freq)
        pi.set_PWM_frequency(self.pin, self.freq)
        if False:
            us = int(1000000 / self.freq / 2)
            self.wave_buzz = []
            self.wave_buzz.append(pigpio.pulse(1<<self.pin, 0, us))
            self.wave_buzz.append(pigpio.pulse(0, 1<<self.pin, us))
            pi.wave_clear()
            pi.wave_add_generic(self.wave_buzz) 
            self.wv = pi.wave_create()

    def buzz(self, state):
        if state:
            pi.set_PWM_dutycycle(self.pin, 50)
        else:
            pi.set_PWM_dutycycle(self.pin, 0)
        if False:
            if state:
                cbs = pi.wave_send_repeat(self.wv)
            else:
                pi.wave_tx_stop()

class BuzzerTimer():
    def __init__(self, c):
        self.c = c
        self.q = queue.Queue()
        self.ts_offset = round(time.time() * 1000)
        self.run_ = False
        self.b = Buzzer(c.rx_tone, c.GPIO_BUZZER_RX)

    def start_loop(self):
        threading.Thread(target=self.buzzer_thread).start()
        
    def stop_loop(self):
        self.run_ = False

    def buzzer_thread(self):
        nx = None
        self.run_ = True
        last_hz = self.c.rx_tone
        while self.run_:
            time.sleep(self.c.sleep_s)
            try:
                nx = self.q.get(block=False)
            except queue.Empty:
                continue
            while (round(time.time() * 1000 < nx[0])):
                   time.sleep(self.c.sleep_s)
            # print(self.run_, nx)
            self.q.task_done()
            if nx[1] == -1:
                break
            elif nx[1] == 1:
                if nx[2] != last_hz:
                    self.b.change_freq(nx[2])
                self.b.buzz(1)
            elif nx[1] == 0:
                self.b.buzz(0)

    def add_to_queue(self, timestamp, status, hz):
        obj = (timestamp, status, hz)
        self.q.put(obj)

    def add_to_queue_offset(self, offset, status, hz):
        self.add_to_queue(offset + self.ts_offset, status, hz)

class VailReader():
    def __init__(self, c):
        self.run_vail_rx = False
        self.offset = 0
        self.cb_ts = (round(time.time() * 1000))
        self.c = c
        self.url = c.ws_url
        self.ws = None
        self.ws_lock = threading.Lock()
        self.backoff = 2
        print("Connecting to", self.url)
        def on_rx_cb(didah, ts, dur):
            data = {"Timestamp": int(ts) + self.cb_ts + self.c.tx_delay - self.offset, "Duration":[dur]}
            data = json.dumps(data)
            with self.ws_lock:
                w = self.ws
            if not w:
                print("tx no ws")
                return
            try:
                w.send(data)
            except WebSocketConnectionClosedException as e:
                print("tx ws closed", e)
                self.drop_ws()
            except Exception as e:
                print("tx send fail", e)
                self.drop_ws()
        self.tmr = BuzzerTimer(c)
        self.kr = KeyReader(c, on_rx_cb)
        self.tmr.start_loop()

    def drop_ws(self):
        with self.ws_lock:
            w = self.ws
            self.ws = None
        if w:
            try:
                w.close()
            except Exception as e:
                print("ws close fail", e)

    def connect_ws(self):
        print("ws connect", self.url)
        try:
            w = create_connection(self.url, subprotocols=["json.vail.woozle.org"], timeout=0.5)
        except Exception as e:
            print("ws connect fail", e)
            return False
        with self.ws_lock:
            self.ws = w
        self.backoff = 2
        print("ws connected")
        return True

    def backoff_wait(self):
        x = self.backoff
        print("ws retry in", x)
        t0 = time.time()
        while self.run_vail_rx and (time.time() - t0) < x:
            time.sleep(0.2)
        if self.backoff < 64:
            self.backoff = self.backoff * 2
            if self.backoff > 64:
                self.backoff = 64

    def stop_rx(self):
        self.tmr.stop_loop()
        time.sleep(0.5)
        self.run_vail_rx = False
        self.drop_ws()
        self.kr.stop_loop()

    def start_rx(self):
        self.run_vail_rx = True
        threading.Thread(target=self.wss_thread, daemon=False).start()

    def wss_thread(self):
        self.run_vail_rx = True
        initial_packet = None
        while self.run_vail_rx:
            with self.ws_lock:
                w = self.ws
            if not w:
                ok = self.connect_ws()
                if ok:
                    initial_packet = None
                    continue
                self.backoff_wait()
                continue
            time.sleep(self.c.sleep_s)
            try:
                d = w.recv()
            except WebSocketTimeoutException:
                continue
            except WebSocketConnectionClosedException as e:
                print("ws recv closed", e)
                self.drop_ws()
                initial_packet = None
                self.backoff_wait()
                continue
            except Exception as e:
                print("ws recv fail", e)
                self.drop_ws()
                initial_packet = None
                self.backoff_wait()
                continue
            # print(d)
            if not d or d.strip() == "":
                continue
            d = json.loads(d)
            if not initial_packet:
                initial_packet = d
                ts = int(d['Timestamp'])
                self.offset = (round(time.time() * 1000)) - ts
                # print("Got timestamp %s, offset=%s" % (ts, self.offset))
            else:
                rx_delay = self.c.rx_delay
                ts_now = rx_delay + int(d['Timestamp']) - self.offset
                d = d['Duration']
                if d:
                    if len(d) == 1:
                        duration = int(d[0])
                        self.tmr.add_to_queue(ts_now, 1, self.c.rx_tone)
                        self.tmr.add_to_queue(ts_now + duration, 0, self.c.rx_tone)
                    else:
                        print("multiple durations not available yet")

def main(fn=None):
    if not fn:
        if len(sys.argv) > 1:
            fn = sys.argv[1]
    if fn:
        c = Cfg(fn)
    else:
        c = Cfg()
    print("cfg", c.fn, c.mode, c.wpm, c.GPIO_DIT, c.GPIO_DAH, c.GPIO_STRAIGHT, c.GPIO_BUZZER_TX, c.GPIO_BUZZER_RX, c.reverse)
    v = VailReader(c)

    try:
        v.start_rx()
        running=True
        while running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("*** Exiting")
    finally:
        v.stop_rx()

if __name__ == "__main__":
    main()
