import socket
import time
from collections import deque


def _osc_string(text: str) -> bytes:
    value = text.encode("utf-8")
    return value + b"\0" * (4 - len(value) % 4)


def chatbox_packet(text: str) -> bytes:
    text = " ".join(text.replace("\0", "").split())
    if len(text.encode("utf-16-le")) > 288:
        prefix = text.encode("utf-16-le")[:286].decode("utf-16-le", errors="ignore")
        text = prefix.rstrip() + "…"
    if not text:
        raise ValueError("Chatbox 文本为空")
    return _osc_string("/chatbox/input") + _osc_string(",sTF") + _osc_string(text)


class ChatboxSender:
    def __init__(self, port: int = 9000):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._address = ("127.0.0.1", port)
        self._pending: deque[str] = deque(maxlen=3)
        self._next_send = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._socket.close()

    def enqueue(self, text: str):
        self._pending.append(text)

    def tick(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self._pending or now < self._next_send:
            return False
        text = self._pending.popleft()
        self._socket.sendto(chatbox_packet(text), self._address)
        self._next_send = now + 1.6
        return True
