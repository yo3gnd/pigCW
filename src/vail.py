#!/usr/bin/env python
import json, logging, queue, sys, threading, time

from websocket import (
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
    create_connection,
)

from .audio_out import AudioToneMix
from .cfg import Config
from .keyer_gpio import KeyerGPIO
from .utils import mono_clock_ms, wall_clock_ms


L = logging.getLogger(__name__)


class ReceiveTonePlayer:
    def __init__(self, config, mix):
        self.config = config
        self.event_queue = queue.Queue()

        self.running = False
        self.tone_output = mix.rx
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
            try:
                item = self.event_queue.get(timeout=self.config.thread_sleep_seconds)
            except queue.Empty:
                continue

            while self.running and wall_clock_ms() < item[0]:
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

        self.session_start_ms = wall_clock_ms()
        self.websocket_url = config.websocket_url
        self.socket = None
        self.socket_lock = threading.Lock()


        self.reconnect_backoff_seconds = 2

        L.info("connecting to %s", self.websocket_url)

        self.aud = AudioToneMix(config)

        self.receive_tone_player = ReceiveTonePlayer(config, self.aud)
        self.keyer = KeyerGPIO(config, self.send_transmit_element, self.aud)

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
            L.warning("tx no ws")
            return

        try:
            socket.send(payload)
        except WebSocketConnectionClosedException as error:
            L.warning("tx ws closed %s", error)
            self.close_socket()
        except Exception as error:
            L.warning("tx send fail %s", error)
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
            L.warning("ws close fail %s", error)

    def connect_socket(self):
        L.info("ws connect %s", self.websocket_url)
        try:
            socket = create_connection(
                self.websocket_url,
                subprotocols=["json.vail.woozle.org"],
                timeout=0.5,
            )
        except Exception as error:
            L.warning("ws connect fail %s", error)
            return False

        with self.socket_lock:
            self.socket = socket

        self.reconnect_backoff_seconds = 2

        L.info("ws connected")
        return True

    def wait_before_reconnect(self):
        wait_seconds = self.reconnect_backoff_seconds
        L.info("ws retry in %s", wait_seconds)

        started_at = mono_clock_ms()
        while self.socket_running and (mono_clock_ms() - started_at) < (wait_seconds * 1000):
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
        self.aud.stop()

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
                L.warning("ws recv closed %s", error)
                self.close_socket()
                first_packet = None
                self.wait_before_reconnect()
                continue
            except Exception as error:
                L.warning("ws recv fail %s", error)
                self.close_socket()
                first_packet = None
                self.wait_before_reconnect()
                continue

            if not payload or payload.strip() == "":
                continue

            try:
                packet = json.loads(payload)
            except Exception as error:
                L.warning("ws json fail %s", error)
                continue

            if first_packet is None:
                first_packet = packet
                timestamp_ms = int(packet["Timestamp"])
                self.clock_offset_ms = wall_clock_ms() - timestamp_ms
                continue

            receive_start_ms = self.config.rx_delay_ms + int(packet["Timestamp"]) - self.clock_offset_ms
            durations = packet["Duration"]

            if not durations:
                continue

            t = receive_start_ms
            tx = 1

            for d in durations:
                d = int(d)

                if d < 0:
                    continue

                if tx and d > 0:
                    self.receive_tone_player.enqueue(t, 1, self.config.rx_tone_hz)
                    self.receive_tone_player.enqueue(t + d, 0, self.config.rx_tone_hz)

                t += d
                tx = not tx


def main(config_path=None):
    if config_path is None and len(sys.argv) > 1:
        config_path = sys.argv[1]

    if config_path:
        config = Config(config_path)
    else:
        config = Config()


    L.info(
        "cfg %s %s %s %s %s %s %s",
        config.path,
        config.keyer_mode,
        config.words_per_minute,
        config.GPIO_DIT,
        config.GPIO_DAH,
        config.GPIO_STRAIGHT,
        config.reverse_paddles,
    )

    client = VailClient(config)


    try:
        print("Starting...")
        client.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("*** Exiting")
    finally:
        client.stop()
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
