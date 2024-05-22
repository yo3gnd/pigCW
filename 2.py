#!/usr/bin/env python
import pigpio, json, os, sys, time
from datetime import datetime
pi = pigpio.pi()
G1=27
G2=4
pi.set_mode(G1, pigpio.OUTPUT)
pi.set_mode(G2, pigpio.OUTPUT)

freq = 740
timing = int(1000000 / freq / 2)
wave_buzz = []
wave_buzz.append(pigpio.pulse(1<<G1, 1<<G2, timing))
wave_buzz.append(pigpio.pulse(1<<G2, 1<<G1, timing))
pi.wave_clear()
pi.wave_add_generic(wave_buzz) # 500 ms flashes
wave_buzz_ = pi.wave_create() # create and save id

for i in range(5):
    cbs = pi.wave_send_repeat(wave_buzz_)
    time.sleep(0.2)
    pi.wave_tx_stop()
    time.sleep(0.2)

pi.set_mode(G1, pigpio.INPUT)
pi.set_mode(G2, pigpio.INPUT)
pi.wave_tx_stop()
pi.wave_clear()
