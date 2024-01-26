import random
import ssl
import websockets
import asyncio
import os
import sys
import json
import argparse

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp

PIPELINE_DESC = '''
webrtcbin name=sendrecv stun-server=stun://stun.l.google.com:19302
 rtspsrc location=rtsp://0.0.0.0:8555/unicast name=demuxer
 demuxer. ! rtpjitterbuffer mode=0 ! queue ! parsebin ! rtph264pay config-interval=-1 timestamp-offset=0 !
  queue ! application/x-rtp,media=video,encoding-name=H264,payload=98 ! queue ! sendrecv.
 demuxer. ! rtpjitterbuffer mode=0 ! queue ! decodebin ! audioconvert ! audioresample ! opusenc ! rtpopuspay timestamp-offset=0 !
  queue ! application/x-rtp,media=audio,encoding-name=OPUS,payload=96 ! queue ! sendrecv.
'''

class WebRTCClient:
    def __init__(self, id_):
        self.id_ = id_
        self.pipe = None
        self.webrtc = None

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        print ('Sending offer:\n%s' % text)
        msg = json.dumps({'sdp': {'type': 'offer', 'sdp': text}})
        # loop = asyncio.new_event_loop()
        # loop.run_until_complete(self.conn.send(msg))

    def on_offer_created(self, promise, _, __):
        print("On offer created")
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        # self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        print("Creating offer")
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        print("send_ice_candidate_message")
        icemsg = json.dumps({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})
        # loop = asyncio.new_event_loop()
        # loop.run_until_complete(self.conn.send(icemsg))

    def on_incoming_stream(self, _, pad):
        print("On incoming stream")
        if pad.direction != Gst.PadDirection.SRC:
            return
        fakesink = Gst.ElementFactory.make('fakesink')
        self.pipe.add(fakesink)
        fakesink.sync_state_with_parent()
        self.webrtc.link(fakesink)

    def start_pipeline(self):
        print("Creating the pipeline")
        self.pipe = Gst.parse_launch(PIPELINE_DESC)
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.on_negotiation_needed(self.webrtc)
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.send_ice_candidate_message)
        self.webrtc.connect('pad-added', self.on_incoming_stream)
        self.pipe.set_state(Gst.State.PLAYING)

    async def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            print ('Received answer:\n%s' % sdp)
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new()
            self.webrtc.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            if message == 'HELLO':
                await self.setup_call()
            elif message == 'SESSION_OK':
                self.start_pipeline()
            elif message.startswith('ERROR'):
                print (message)
                return 1
            else:
                await self.handle_sdp(message)
        return 0


def check_plugins():
    needed = ["opus", "vpx", "nice", "webrtc", "dtls", "srtp", "rtp",
              "rtpmanager", "videotestsrc", "audiotestsrc"]
    missing = list(filter(lambda p: Gst.Registry.get().find_plugin(p) is None, needed))
    if len(missing):
        print('Missing gstreamer plugins:', missing)
        return False
    return True


if __name__=='__main__':
    Gst.init(None)
    if not check_plugins():
        sys.exit(1)
    loop = asyncio.get_event_loop()
    client_id = "webrtc gstreamer"
    pc = WebRTCClient(client_id)
    pc.start_pipeline()
    loop.run_forever()
    sys.exit(res)