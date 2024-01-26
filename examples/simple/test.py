



import time

import gi
from gi.repository import GLib
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC

from webrtc import WebRTC
from webrtc import TestSource, RTSPSource

loop = GLib.MainLoop()


pc = WebRTC()

@pc.on('offer')
def on_offer(offer):
    print(offer)
    print(offer.sdp.as_text())

@pc.on('answer')
def on_answer(answer):
    print(answer)

# pc.add_transceiver(WebRTC.RECVONLY, 'H264')
# pc.add_transceiver(WebRTC.RECVONLY, 'OPUS')


time.sleep(1)

pc.create_offer()

url = "rtsp://0.0.0.0:8555/unicast"
source  = RTSPSource(url)
# source = TestSource()

pc.add_stream(source)

time.sleep(1)

pc.create_offer()

time.sleep(1)

pc.remove_stream(source)



loop.run()
