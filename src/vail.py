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
THREAD_SLEEP = 0.01
GPIO_BUZZER = 27
GPIO_DIT=26
GPIO_DAH=16
REPEATER="General"
URL = "wss://vail.woozle.org/chat"
URL+= "?repeater=" + REPEATER

running = False

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

class PaddleReader():
    def __init__(self, c, cb):

            self.cb = cb
            self.c = c
            self.q = queue.Queue()
            pi.set_pull_up_down(c.get("gpio_dit"), pigpio.PUD_UP)
            pi.set_glitch_filter(c.get("gpio_dit"), c.get("glitch_filter_dit"))
            pi.set_pull_up_down(c.get("gpio_dah"), pigpio.PUD_UP)
            pi.set_glitch_filter(c.get("gpio_dah"), c.get("glitch_filter_dah"))

            self.gpio_dit = c.get("gpio_dit")
            self.gpio_dah = c.get("gpio_dah")

            def cbf_delegate(gpio, level, tick):
                self.cbf(gpio, level, tick)
                if gpio == self.gpio_dit:
                    bp = 1
                    # print("dit")
                elif gpio == self.gpio_dah:
                    bp = 1
                    # print("dah")

            self.cb_dit = pi.callback(GPIO_DIT, pigpio.EITHER_EDGE, cbf_delegate)
            self.cb_dah = pi.callback(GPIO_DAH, pigpio.EITHER_EDGE, cbf_delegate)

            self.start_loop()

    def __del__(self):
        pass
        # self.cb_dit.cancel()
        # self.cb_dah.cancel()

    def start_loop(self):
        self.run = True
        threading.Thread(target=self.paddle_thread, daemon=False).start()
        
    def stop_loop(self):
        self.run = False

    def cbf(self, gpio, level, tick):
       obj = (gpio, not level, tick)
       self.q.put(obj)

    def paddle_thread(self):
        dit_start = 0
        dah_start = 0
        ts_offset = pi.get_current_tick()
        while self.run:
            time.sleep(0.001)
            try:
                nx = self.q.get(block=False)
            except queue.Empty:
                continue
            gpio = nx[0]
            dit = None
            gpiotick = nx[2]
            if gpio == self.gpio_dit:
                dit = True
            elif gpio == self.gpio_dah:
                dit = False

            if not nx[1]:
                if dit:
                    delta = abs(int(pigpio.tickDiff(dit_start, gpiotick)/1000))
                    self.cb(0, round((dit_start - ts_offset)/1000), delta)
                    dit_start = 0
                else:
                    delta = abs(int(pigpio.tickDiff(dah_start, gpiotick)/1000))
                    x = round((dah_start - ts_offset)/1000)
                    # print("x=", x, "dah_start=", dah_start)
                    # print(ts_offset)
                    self.cb(1, x, delta)
                    dah_start = 0
            else:
                if dit:
                    dit_start = gpiotick
                else:
                    dah_start = gpiotick
            self.q.task_done()

class Buzzer():
    def __init__(self, c, freq):
        self.c = c
        self.pin = c.get("gpio_buzzer")
        pi.set_mode(self.pin, pigpio.OUTPUT)
        self.change_freq(freq)

    def change_freq(self, freq):
        self.freq = int(freq)
        us = int(1000000 / self.freq / 2)
        self.wave_buzz = []
        self.wave_buzz.append(pigpio.pulse(1<<self.pin, 0, us))
        self.wave_buzz.append(pigpio.pulse(0, 1<<self.pin, us))
        pi.wave_clear()
        pi.wave_add_generic(self.wave_buzz) 
        self.wv = pi.wave_create()

    def buzz(self, state):
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
        self.b = Buzzer(c, c.get("rxtone"))

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
        self.url = self.c.get("url") + "?repeater=" + self.c.get("repeater")
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
        self.pd = PaddleReader(c, on_rx_cb)
        self.tmr.start_loop()

    def stop_rx(self):
        self.tmr.stop_loop()
        time.sleep(0.5)
        self.run_vail_rx = False
        self.ws.close()
        self.pd.stop_loop()

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
    global running
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
