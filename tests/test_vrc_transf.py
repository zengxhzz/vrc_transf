import json
import socket
import unittest
from base64 import b64decode

from vrc_transf.audio import PcmConverter
from vrc_transf.osc import ChatboxSender, chatbox_packet
from vrc_transf.translation import QwenEvents, QwenSettings, audio_event


class QwenTests(unittest.TestCase):
    def test_qianwen_china_uses_fixed_host_without_a_workspace(self):
        settings = QwenSettings(api_key="test", workspace="", region="qianwen-cn")
        self.assertEqual(
            settings.url,
            "wss://maas.qianwenaiapi.com/api-ws/v1/realtime?model=qwen3.8-livetranslate-flash-realtime",
        )

    def test_model_studio_still_requires_a_workspace(self):
        with self.assertRaises(ValueError):
            QwenSettings(api_key="test", workspace="", region="cn-beijing")

    def test_partial_and_completed_text_have_distinct_events(self):
        events = QwenEvents()
        partial = events.feed({"type": "response.text.delta", "response_id": "r1", "delta": "今"})
        self.assertEqual((partial.kind, partial.text), ("partial", "今"))
        partial = events.feed({"type": "response.text.delta", "response_id": "r1", "delta": "晚"})
        self.assertEqual(partial.text, "今晚")
        self.assertIsNone(events.feed({"type": "response.text.done", "response_id": "r1", "text": "今晚见"}))
        completed = {"type": "response.done", "response": {"id": "r1", "status": "completed"}}
        final = events.feed(completed)
        self.assertEqual((final.kind, final.text), ("final", "今晚见"))
        self.assertIsNone(events.feed(completed))

    def test_interrupted_response_never_becomes_final(self):
        events = QwenEvents()
        events.feed({"type": "response.text.done", "response_id": "r1", "text": "an interrupted line"})
        result = events.feed({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}})
        self.assertEqual((result.kind, result.text), ("discard", ""))

    def test_settings_request_text_translation_at_16khz(self):
        settings = QwenSettings(api_key="test", workspace="llm-example", region="cn-beijing")
        self.assertEqual(settings.url, "wss://llm-example.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen3.8-livetranslate-flash-realtime")
        session = settings.session_update("ja")["session"]
        self.assertEqual(session["output_modalities"], ["text"])
        self.assertEqual(session["translation"], {"language": "ja"})
        self.assertEqual(session["audio"]["input"]["format"], {"type": "pcm", "sample_rate": 16000})
        with self.assertRaises(ValueError):
            QwenSettings(api_key="test", workspace="example.org/path", region="cn-beijing")

    def test_audio_frames_are_base64_encoded_without_reinterpretation(self):
        event = json.loads(audio_event(b"\x01\x00\xff\xff"))
        self.assertEqual(event["type"], "input_audio_buffer.append")
        self.assertEqual(b64decode(event["audio"]), b"\x01\x00\xff\xff")


class OscTests(unittest.TestCase):
    def test_utf8_osc_packet_and_chatbox_flags(self):
        self.assertEqual(chatbox_packet("你好"), b"/chatbox/input\0\0,sTF\0\0\0\0" + "你好".encode() + b"\0\0")

    def test_long_text_does_not_split_surrogate_pairs(self):
        text = ("a" * 142) + "🌏" + "x"
        payload = chatbox_packet(text)[24:].rstrip(b"\0").decode()
        self.assertEqual(payload, ("a" * 142) + "…")

    def test_sender_rate_limits_and_delivers_pending_text_over_udp(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(0.5)
            with ChatboxSender(port=receiver.getsockname()[1]) as sender:
                sender.enqueue("first")
                sender.enqueue("second")
                self.assertTrue(sender.tick(10.0))
                self.assertEqual(receiver.recv(1024), chatbox_packet("first"))
                self.assertFalse(sender.tick(10.1))
                self.assertTrue(sender.tick(12.0))
                self.assertEqual(receiver.recv(1024), chatbox_packet("second"))


class AudioTests(unittest.TestCase):
    def test_stereo_audio_downmixes_to_mono(self):
        converter = PcmConverter(16000, 2)
        pcm = b"\xe8\x03\x18\xfc\xd0\x07\xd0\x07"
        self.assertEqual(converter.convert(pcm), b"\x00\x00\xd0\x07")

    def test_resampling_preserves_audios_duration_across_chunks(self):
        converter = PcmConverter(48000, 1)
        data = b"\x00\x00" * 4800
        output = b"".join(converter.convert(data) for _ in range(10)) + converter.finish()
        self.assertEqual(len(output), 32000)
