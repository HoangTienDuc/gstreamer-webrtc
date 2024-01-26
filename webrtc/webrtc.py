

from gi.repository import GLib
from gi.repository import GstSdp
from gi.repository import GstWebRTC
from gi.repository import Gst
from gi.repository import GObject
import asyncio
import os
import sys
import attr
from pyee import EventEmitter
import gi
gi.require_version('GObject', '2.0')
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')

Gst.init(None)


PIPELINE_DESC = '''
webrtcbin name=sendrecv stun-server=stun://stun.l.google.com:19302
 rtspsrc location=rtsp://0.0.0.0:8555/unicast name=demuxer
 demuxer. ! rtpjitterbuffer mode=0 ! queue ! parsebin ! rtph264pay config-interval=-1 timestamp-offset=0 !
  queue ! application/x-rtp,media=video,encoding-name=H264,payload=98 ! queue ! sendrecv.
 demuxer. ! rtpjitterbuffer mode=0 ! queue ! decodebin ! audioconvert ! audioresample ! opusenc ! rtpopuspay timestamp-offset=0 !
  queue ! application/x-rtp,media=audio,encoding-name=OPUS,payload=96 ! queue ! sendrecv.
'''


class WebRTC(EventEmitter):
    def __init__(self, outsink=None, stun_server=None, turn_server=None,):
        super().__init__()

        self.stun_server = stun_server
        self.turn_server = turn_server
        self.streams = []

        self.pipe = Gst.parse_launch(PIPELINE_DESC)
        self.webrtc = self.pipe.get_by_name('sendrecv')

        self.webrtc.connect('on-negotiation-needed',
                            self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.webrtc.connect('pad-added', self.on_add_stream)
        self.webrtc.connect('pad-removed', self.on_remove_stream)

        if self.stun_server:
            self.webrtc.set_property('stun-server', self.stun_server)

        if self.turn_server:
            self.webrtc.set_property('turn-server', self.turn_server)

        # self.webrtc.set_property('bundle-policy','max-bundle')

        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self._bus_call, None)

        self.pipe.set_state(Gst.State.PLAYING)

    @property
    def connection_state(self):
        return self.webrtc.get_property('connection-state')

    @property
    def ice_connection_state(self):
        return self.webrtc.get_property('ice-connection-state')

    @property
    def local_description(self):
        return self.webrtc.get_property('local-description')

    @property
    def remote_description(self):
        return self.webrtc.get_property('remote-description')

    def on_negotiation_needed(self, element):
        self.emit('negotiation-needed', element)

    def on_ice_candidate(self, element, mlineindex, candidate):
        self.emit('candidate', {
            'sdpMLineIndex': mlineindex,
            'candidate': candidate
        })

    def add_transceiver(self, direction, codec):
        upcodec = codec.upper()
        caps = None
        if upcodec == 'H264':
            caps = H264_CAPS
        elif upcodec == 'VP8':
            caps = VP8_CAPS
        elif upcodec == 'OPUS':
            caps = OPUS_CAPS
        return self.webrtc.emit('add-transceiver', direction, caps)

    def create_offer(self):
        promise = Gst.Promise.new_with_change_func(
            self.on_offer_created, self.webrtc, None)
        self.webrtc.emit('create-offer', None, promise)

    def on_offer_created(self, promise, element, _):
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')
        if offer:
            self.emit('offer', offer)


    def create_answer(self):
        promise = Gst.Promise.new_with_change_func(
            self.on_answer_created, self.webrtc, None)
        self.webrtc.emit('create-answer', None, promise)

    def on_answer_created(self, promise, element, _):
        ret = promise.wait()
        if ret != Gst.PromiseResult.REPLIED:
            return
        reply = promise.get_reply()
        answer = reply.get_value('answer')
        if answer:
            self.emit('answer', answer)

    def add_ice_candidate(self, ice):
        sdpMLineIndex = ice['sdpMLineIndex']
        candidate = ice['candidate']
        self.webrtc.emit('add-ice-candidate', sdpMLineIndex, candidate)

    def set_local_description(self, sdp):
        # promise = Gst.Promise.new_with_change_func(self.set_description_result, self.webrtc, None)
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', sdp, promise)
        promise.interrupt()

    def set_remote_description(self, sdp):
        # promise = Gst.Promise.new_with_change_func(self.set_description_result, self.webrtc, None)
        promise = Gst.Promise.new()
        self.webrtc.emit('set-remote-description', sdp, promise)
        promise.interrupt()

    def get_stats(self):
        pass

    def set_description_result(self, promise, element, _):
        ret = promise.wait()
        if ret != Gst.PromiseResult.REPLIED:
            return
        reply = promise.get_reply()

    def _bus_call(self, bus, message, _):
        t = message.type
        if t == Gst.MessageType.EOS:
            print('End-of-stream')
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print('Error: %s: %s\n' % (err, debug))
        return True

    def on_add_stream(self, element, pad):
        print("On incoming stream")
        if pad.direction != Gst.PadDirection.SRC:
            return
        fakesink = Gst.ElementFactory.make('fakesink')
        self.pipe.add(fakesink)
        fakesink.sync_state_with_parent()
        self.webrtc.link(fakesink)

    def on_remove_stream(self, element, pad):
        # local stream
        if pad.direction == Gst.PadDirection.SINK:
            return
