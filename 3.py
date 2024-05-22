#!/usr/bin/env python
import pigpio, json, os, sys, time
from datetime import datetime
pi = pigpio.pi()
G1=27
G2=4

GPIO_DIT=26
GPIO_DAH=16

pi.set_pull_up_down(GPIO_DIT, pigpio.PUD_UP)
pi.set_glitch_filter(GPIO_DIT, 1000*10)

def cbf(gpio, level, tick):
   print(gpio, level, tick)

cb1 = pi.callback(GPIO_DIT, pigpio.EITHER_EDGE, cbf)

time.sleep(25)
cb1.cancel()
