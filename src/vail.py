#!/usr/bin/env python
import pigpio, json, os, sys, time, queue, threading, signal, configparser
from datetime import datetime
from websocket import create_connection, WebSocketTimeoutException

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
conf_file = os.path.join(root, "pigcw.conf")

pi = pigpio.pi()

RX_DELAY = 1000
TX_DELAY = 2000
RX_TONE = 523
TX_TONE = 740
THREAD_SLEEP = 0.01
GPIO_BUZZER = 27
GPIO_BUZZER_TX = 27
GPIO_BUZZER_RX = 22
GPIO_DIT=26
GPIO_DAH=16
GPIO_STRAIGHT=20
GLITCH_FILTER_STRAIGHT=5000
REVERSE_PADDLES = 0
KEYER_MODE = "a"
STRAIGHT_DISABLE_MS = 1000
WPM = 20
DIT_MS = 60
DAH_MS = 180
ELEMENT_SPACE_MS = 60
REPEATER="General"
URL = "wss://vail.woozle.org/chat"
URL+= "?repeater=" + REPEATER

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

class ConfigLoader():
    def __init__(self, fn=conf_file):
        self.fn = fn
        self.cp = configparser.ConfigParser()
        self.cp.read(fn)
        self.d = dict(self.cp.items('general'))
        for i, k in enumerate(self.d):
            val = self.d[k]
            try:
                val=float(val)
                if val.is_integer():
                    val = int(val)
            except ValueError:
                pass
            self.d[k] = val

    def get(self, var):
        if var in self.d:

            return self.d.get(var)
        else:
            return None

class KeyReader():
    def __init__(self, c, cb):

            self.cb = cb
            self.c = c
            self.q = queue.Queue()
            self.btx = Buzzer(TX_TONE, GPIO_BUZZER_TX)
            self.base_ms = round(time.time() * 1000)
            self.gpio_dit = c.get("gpio_dit")
            self.gpio_dah = c.get("gpio_dah")
            self.gpio_straight = c.get("gpio_straight")
            pi.set_pull_up_down(self.gpio_dit, pigpio.PUD_UP)
            pi.set_glitch_filter(self.gpio_dit, c.get("glitch_filter_dit"))
            pi.set_pull_up_down(self.gpio_dah, pigpio.PUD_UP)
            pi.set_glitch_filter(self.gpio_dah, c.get("glitch_filter_dah"))
            pi.set_pull_up_down(self.gpio_straight, pigpio.PUD_UP)
            pi.set_glitch_filter(self.gpio_straight, c.get("glitch_filter_straight"))

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
        if KEYER_MODE == "a":
            s = "mode a mem"
        elif KEYER_MODE == "b":
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
        self.btx.buzz(0)

    def next_kind(self):
        global dit_down, dah_down, last_repeat, ka_q
        if KEYER_MODE == "keyahead":
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
        self.btx.change_freq(TX_TONE)
        self.btx.buzz(1)
        if kind == "dit":
            print("tx start dit", tick, DIT_MS)
            sending_end_tick = now + DIT_MS
            if KEYER_MODE == "b" and dah_down:
                self.set_mem("dah")
        else:
            print("tx start dah", tick, DAH_MS)
            sending_end_tick = now + DAH_MS
            if KEYER_MODE == "b" and dit_down:
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
        space_end_tick = now + ELEMENT_SPACE_MS

    def handle_deadline(self):
        global sending, sending_kind, space_end_tick
        now = round(time.time() * 1000)
        if straight_down:
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
            self.btx.change_freq(TX_TONE)
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
            straight_until = now + STRAIGHT_DISABLE_MS
            print("straight inhibit", straight_until)

    def handle_paddle(self, kind, pressed, tick, now):
        global dit_down, dah_down, ka_q
        if REVERSE_PADDLES:
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

            if KEYER_MODE == "keyahead":
                ka_q.append(kind)
                print("ka push", kind)
            elif sending and sending_kind and kind != sending_kind:
                if KEYER_MODE == "a":
                    if not was:
                        self.set_mem(kind)
                elif KEYER_MODE == "b":
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
        self.b = Buzzer(RX_TONE, GPIO_BUZZER_RX)

    def start_loop(self):
        threading.Thread(target=self.buzzer_thread).start()
        
    def stop_loop(self):
        self.run_ = False

    def buzzer_thread(self):
        nx = None
        self.run_ = True
        last_hz = RX_TONE
        while self.run_:
            time.sleep(THREAD_SLEEP)
            try:
                nx = self.q.get(block=False)
            except queue.Empty:
                continue
            while (round(time.time() * 1000 < nx[0])):
                   time.sleep(THREAD_SLEEP)
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
        self.url = URL + "?repeater=" + REPEATER
        print("Connecting to", self.url)
        def on_rx_cb(didah, ts, dur):
            data = {"Timestamp": int(ts) + self.cb_ts + TX_DELAY - self.offset, "Duration":[dur]}
            data = json.dumps(data)
            try:
                self.ws.send(data)
            except WebSocketConnectionClosedException:
                self.run_vail_rx = False
                print("*** Remote socket closed")
                v.stop_rx()
        
        self.ws = create_connection(self.url, subprotocols=["json.vail.woozle.org"], timeout=0.5)
        self.tmr = BuzzerTimer(c)
        self.kr = KeyReader(c, on_rx_cb)
        self.tmr.start_loop()

    def stop_rx(self):
        self.tmr.stop_loop()
        time.sleep(0.5)
        self.run_vail_rx = False
        self.ws.close()
        self.kr.stop_loop()

    def start_rx(self):
        self.run_vail_rx = True
        threading.Thread(target=self.wss_thread, daemon=False).start()

    def wss_thread(self):
        self.run_vail_rx = True
        initial_packet = None
        offset = -1
        while self.run_vail_rx:
            time.sleep(THREAD_SLEEP)
            try:
                d = self.ws.recv()
            except WebSocketTimeoutException:
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
                rx_delay = RX_DELAY
                ts_now = rx_delay + int(d['Timestamp']) - self.offset
                d = d['Duration']
                if d:
                    if len(d) == 1:
                        duration = int(d[0])
                        f = 740
                        self.tmr.add_to_queue(ts_now, 1, RX_TONE)
                        self.tmr.add_to_queue(ts_now + duration, 0, RX_TONE)
                    else:
                        print("multiple durations not available yet")

def main():
    c = ConfigLoader()
    global running, RX_DELAY, TX_DELAY, RX_TONE, TX_TONE, THREAD_SLEEP
    global GPIO_BUZZER, GPIO_BUZZER_TX, GPIO_BUZZER_RX, GPIO_DIT, GPIO_DAH, GPIO_STRAIGHT
    global GLITCH_FILTER_STRAIGHT, REVERSE_PADDLES, KEYER_MODE, STRAIGHT_DISABLE_MS
    global WPM, DIT_MS, DAH_MS, ELEMENT_SPACE_MS, REPEATER, URL
    RX_DELAY = c.get("rxdelay")
    TX_DELAY = c.get("txdelay")
    RX_TONE = c.get("rxtone")
    TX_TONE = c.get("txtone")
    THREAD_SLEEP = c.get("thread_sleep")
    GPIO_BUZZER = c.get("gpio_buzzer")
    GPIO_BUZZER_TX = c.get("gpio_buzzer_tx")
    GPIO_BUZZER_RX = c.get("gpio_buzzer_rx")
    GPIO_DIT = c.get("gpio_dit")
    GPIO_DAH = c.get("gpio_dah")
    GPIO_STRAIGHT = c.get("gpio_straight")
    GLITCH_FILTER_STRAIGHT = c.get("glitch_filter_straight")
    REVERSE_PADDLES = c.get("reverse_paddles")
    KEYER_MODE = c.get("keyer_mode")
    STRAIGHT_DISABLE_MS = c.get("straight_disable_ms")
    WPM = c.get("wpm")
    DIT_MS = round(1200 / WPM)
    DAH_MS = DIT_MS * 3
    ELEMENT_SPACE_MS = DIT_MS
    REPEATER = c.get("repeater")
    URL = c.get("url")
    print("cfg", KEYER_MODE, WPM, GPIO_DIT, GPIO_DAH, GPIO_STRAIGHT, GPIO_BUZZER_TX, GPIO_BUZZER_RX, REVERSE_PADDLES)
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

# def main2():
#     d = CWDecoder()

if __name__ == "__main__":
    main()
    # if False:
    #     main2()
