#!/usr/bin/env python
import json
import queue
import sys
import threading
import time

import pigpio
from websocket import (
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
    create_connection,
)

from .cfg import Config

from .keyer_engine import KeyerEngine


gpio = pigpio.pi()


class Keyer:
    def __init__(self, config, on_element):
        self.config = config
        self.on_element = on_element

        self.event_queue = queue.Queue()
        self.tone_output = ToneOutput(config.tx_tone_hz, config.GPIO_BUZZER_TX)
        self.session_start_ms = round(time.time() * 1000)
        self.eng = KeyerEngine(config, self.tone_output, on_element, gpio)

        self.dit_pin = config.GPIO_DIT
        self.dah_pin = config.GPIO_DAH


        self.straight_pin = config.GPIO_STRAIGHT

        gpio.set_pull_up_down(self.dit_pin, pigpio.PUD_UP)
        gpio.set_glitch_filter(self.dit_pin, config.dit_glitch_filter)

        gpio.set_pull_up_down(self.dah_pin, pigpio.PUD_UP)
        gpio.set_glitch_filter(self.dah_pin, config.dah_glitch_filter)

        gpio.set_pull_up_down(self.straight_pin, pigpio.PUD_UP)
        gpio.set_glitch_filter(self.straight_pin, config.straight_glitch_filter)

        self.dit_callback = gpio.callback(
            self.dit_pin,
            pigpio.EITHER_EDGE,
            lambda pin, level, tick: self.enqueue_edge("dit", level, tick),
        )
        self.dah_callback = gpio.callback(
            self.dah_pin,
            pigpio.EITHER_EDGE,
            lambda pin, level, tick: self.enqueue_edge("dah", level, tick),
        )
        self.straight_callback = gpio.callback(
            self.straight_pin,
            pigpio.EITHER_EDGE,
            lambda pin, level, tick: self.enqueue_edge("straight", level, tick),
        )

        self.running = False
        self.thread = None

        self.start()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.worker_loop, daemon=False)
        self.thread.start()

    def stop(self):
        self.running = False
        self.tone_output.set_enabled(False)

        self.dit_callback.cancel()
        self.dah_callback.cancel()
        self.straight_callback.cancel()

    def enqueue_edge(self, kind, level, tick):
        self.event_queue.put((kind, not level, tick))

    def worker_loop(self):
        while self.running:
            try:
                kind, pressed, gpio_tick = self.event_queue.get(timeout=self.eng.wait_s())
            except queue.Empty:
                self.eng.timer_ev()
                continue

            now_ms = round(time.time() * 1000)

            if kind == "straight":
                self.eng.straight_ev(pressed, gpio_tick, now_ms)
                self.event_queue.task_done()
                self.eng.timer_ev()
                continue

            self.eng.paddle_ev(kind, pressed, gpio_tick, now_ms)
            self.event_queue.task_done()
            self.eng.timer_ev()


class ToneOutput:
    def __init__(self, frequency_hz, pin):
        self.pin = pin
        gpio.set_mode(self.pin, pigpio.OUTPUT)
        gpio.set_PWM_range(self.pin, 100)

        self.set_frequency(frequency_hz)

    def set_frequency(self, frequency_hz):
        self.frequency_hz = int(frequency_hz)
        gpio.set_PWM_frequency(self.pin, self.frequency_hz)

    def set_enabled(self, enabled):
        if enabled:
            gpio.set_PWM_dutycycle(self.pin, 50)
        else:
            gpio.set_PWM_dutycycle(self.pin, 0)


class ReceiveTonePlayer:
    def __init__(self, config):
        self.config = config
        self.event_queue = queue.Queue()

        self.running = False
        self.tone_output = ToneOutput(config.rx_tone_hz, config.GPIO_BUZZER_RX)
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.player_loop)

        self.thread.start()

    def stop(self):
        self.running = False
        self.tone_output.set_enabled(False)

    def player_loop(self):
        self.running = True
        last_frequency_hz = self.config.rx_tone_hz


        while self.running:
            time.sleep(self.config.thread_sleep_seconds)
            try:
                item = self.event_queue.get(block=False)
            except queue.Empty:
                continue

            while self.running and round(time.time() * 1000) < item[0]:
                time.sleep(self.config.thread_sleep_seconds)

            self.event_queue.task_done()
            if not self.running:
                break


            if item[1] == 1:
                if item[2] != last_frequency_hz:
                    self.tone_output.set_frequency(item[2])
                    last_frequency_hz = item[2]

                self.tone_output.set_enabled(True)
            elif item[1] == 0:
                self.tone_output.set_enabled(False)

    def enqueue(self, timestamp_ms, enabled, frequency_hz):
        self.event_queue.put((timestamp_ms, enabled, frequency_hz))


class VailClient:
    def __init__(self, config):
        self.config = config
        self.socket_running = False
        self.clock_offset_ms = 0

        self.session_start_ms = round(time.time() * 1000)
        self.websocket_url = config.websocket_url
        self.socket = None
        self.socket_lock = threading.Lock()


        self.reconnect_backoff_seconds = 2

        print("Connecting to", self.websocket_url)

        self.receive_tone_player = ReceiveTonePlayer(config)
        self.keyer = Keyer(config, self.send_transmit_element)

        self.receive_tone_player.start()

    def send_transmit_element(self, _element_kind, start_offset_ms, duration_ms):
        packet = {
            "Timestamp": int(start_offset_ms) + self.session_start_ms + self.config.tx_delay_ms - self.clock_offset_ms,
            "Duration": [duration_ms],
        }
        payload = json.dumps(packet)

        with self.socket_lock:
            socket = self.socket

        if not socket:
            print("tx no ws")
            return

        try:
            socket.send(payload)
        except WebSocketConnectionClosedException as error:
            print("tx ws closed", error)
            self.close_socket()
        except Exception as error:
            print("tx send fail", error)
            self.close_socket()

    def close_socket(self):
        with self.socket_lock:
            socket = self.socket
            self.socket = None


        if not socket:
            return

        try:
            socket.close()
        except Exception as error:
            print("ws close fail", error)

    def connect_socket(self):
        print("ws connect", self.websocket_url)
        try:
            socket = create_connection(
                self.websocket_url,
                subprotocols=["json.vail.woozle.org"],
                timeout=0.5,
            )
        except Exception as error:
            print("ws connect fail", error)
            return False

        with self.socket_lock:
            self.socket = socket

        self.reconnect_backoff_seconds = 2

        print("ws connected")
        return True

    def wait_before_reconnect(self):
        wait_seconds = self.reconnect_backoff_seconds
        print("ws retry in", wait_seconds)

        started_at = time.time()
        while self.socket_running and (time.time() - started_at) < wait_seconds:
            time.sleep(0.2)

        if self.reconnect_backoff_seconds < 64:
            self.reconnect_backoff_seconds = self.reconnect_backoff_seconds * 2
            if self.reconnect_backoff_seconds > 64:
                self.reconnect_backoff_seconds = 64

    def start(self):
        self.socket_running = True
        threading.Thread(target=self.socket_loop, daemon=False).start()

    def stop(self):
        self.receive_tone_player.stop()
        time.sleep(0.5)

        self.socket_running = False
        self.close_socket()
        self.keyer.stop()

    def socket_loop(self):
        self.socket_running = True
        first_packet = None

        while self.socket_running:
            with self.socket_lock:
                socket = self.socket


            if not socket:
                connected = self.connect_socket()
                if connected:
                    first_packet = None
                    continue
                self.wait_before_reconnect()
                continue

            time.sleep(self.config.thread_sleep_seconds)

            try:
                payload = socket.recv()
            except WebSocketTimeoutException:
                continue
            except WebSocketConnectionClosedException as error:
                print("ws recv closed", error)
                self.close_socket()
                first_packet = None
                self.wait_before_reconnect()
                continue
            except Exception as error:
                print("ws recv fail", error)
                self.close_socket()
                first_packet = None
                self.wait_before_reconnect()
                continue

            if not payload or payload.strip() == "":
                continue

            packet = json.loads(payload)
            if not first_packet:
                first_packet = packet
                timestamp_ms = int(packet["Timestamp"])
                self.clock_offset_ms = round(time.time() * 1000) - timestamp_ms
                continue

            receive_start_ms = self.config.rx_delay_ms + int(packet["Timestamp"]) - self.clock_offset_ms
            durations = packet["Duration"]

            if not durations:
                continue

            if len(durations) != 1:
                print("multiple durations not available yet")
                continue

            duration_ms = int(durations[0])
            self.receive_tone_player.enqueue(receive_start_ms, 1, self.config.rx_tone_hz)
            self.receive_tone_player.enqueue(receive_start_ms + duration_ms, 0, self.config.rx_tone_hz)


def main(config_path=None):
    if config_path is None and len(sys.argv) > 1:
        config_path = sys.argv[1]

    if config_path:
        config = Config(config_path)
    else:
        config = Config()


    print(
        "cfg",
        config.path,
        config.keyer_mode,
        config.words_per_minute,
        config.GPIO_DIT,
        config.GPIO_DAH,
        config.GPIO_STRAIGHT,
        config.GPIO_BUZZER_TX,
        config.GPIO_BUZZER_RX,
        config.reverse_paddles,
    )

    client = VailClient(config)


    try:
        client.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("*** Exiting")
    finally:
        client.stop()


if __name__ == "__main__":
    main()
