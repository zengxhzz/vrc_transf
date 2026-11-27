import json
import unittest
from contextlib import contextmanager
from threading import Event, Thread

from websockets.sync.client import connect
from websockets.sync.server import serve

from vrc_transf.audio import AudioFrames, PcmConverter
from vrc_transf.translation import QwenSettings, QwenTranslator


class StreamingTests(unittest.TestCase):
    def test_qwen_session_streams_audio_then_waits_for_final_translation_on_stop(self):
        upstream_events = []
        stop = Event()
        capture_closed = Event()

        @contextmanager
        def input_stream():
            frames = AudioFrames()
            frames.converter = PcmConverter(16000, 1)
            frames.push(b"\x01\x00" * 640)
            try:
                yield frames
            finally:
                capture_closed.set()

        def fake_provider(connection):
            connection.send('{"type":"session.created"}')
            upstream_events.append(json.loads(connection.recv(timeout=2)))
            connection.send('{"type":"session.updated"}')
            upstream_events.append(json.loads(connection.recv(timeout=2)))
            connection.send('{"type":"response.text.delta","response_id":"r1","delta":"See"}')
            while True:
                event = json.loads(connection.recv(timeout=2))
                upstream_events.append(event)
                if event["type"] == "session.finish":
                    break
            connection.send('{"type":"response.text.done","response_id":"r1","text":"See you!"}')
            connection.send('{"type":"response.done","response":{"id":"r1","status":"completed"}}')
            connection.send('{"type":"session.finished"}')

        translator = QwenTranslator(QwenSettings("test", "llm-test", "cn-beijing"))
        received = []
        with serve(fake_provider, "127.0.0.1", 0) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            try:
                port = server.socket.getsockname()[1]
                with connect(f"ws://127.0.0.1:{port}", proxy=None) as connection:
                    for event in translator._exchange(connection, "en", input_stream, stop):
                        received.append((event.kind, event.text))
                        if event.kind == "partial":
                            stop.set()
            finally:
                server.shutdown()
                worker.join()

        self.assertTrue(capture_closed.is_set())
        self.assertEqual(received, [("ready", ""), ("partial", "See"), ("final", "See you!")])
        self.assertEqual(upstream_events[0]["session"]["translation"], {"language": "en"})
        self.assertEqual(upstream_events[1]["type"], "input_audio_buffer.append")
        self.assertEqual(upstream_events[-1], {"type": "session.finish"})
