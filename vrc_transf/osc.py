import socket
import time
from collections import deque
from dataclasses import dataclass

MAX_TEXT_BYTES = 144 * 2  # Chatbox counts UTF-16 code units.


def _osc_string(text: str) -> bytes:
    value = text.encode("utf-8")
    return value + b"\0" * (4 - len(value) % 4)


def _display_text(text: str) -> str:
    text = " ".join(text.replace("\0", "").split())
    encoded = text.encode("utf-16-le", errors="replace")
    if len(encoded) > MAX_TEXT_BYTES:
        prefix = encoded[:MAX_TEXT_BYTES - 2].decode("utf-16-le", errors="ignore")
        return prefix.rstrip() + "…"
    return encoded.decode("utf-16-le")


def chatbox_packet(text: str) -> bytes:
    text = _display_text(text)
    if not text:
        raise ValueError("Chatbox 文本为空")
    return _osc_string("/chatbox/input") + _osc_string(",sTF") + _osc_string(text)


@dataclass
class _Message:
    text: str
    mergeable: bool
    sent: bool = False


class ChatboxSender:
    def __init__(self, port: int = 9000):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._address = ("127.0.0.1", port)
        # Keep one slot per original enqueue. Merged lines share the same packet.
        self._slots: deque[_Message] = deque(maxlen=3)
        self._next_slot = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._socket.close()

    def finish_session(self):
        # Keep unsent text, but prevent the next session from joining this packet.
        if self._slots:
            self._slots[-1].mergeable = False

    def enqueue(self, text: str, *, mergeable: bool = False):
        text = _display_text(text)
        if not text:
            return
        previous = self._slots[-1] if self._slots else None
        if mergeable and previous and previous.mergeable and not previous.sent:
            combined = previous.text + " " + text
            if len(combined.encode("utf-16-le")) <= MAX_TEXT_BYTES:
                previous.text = combined
                self._slots.append(previous)
                return
        self._slots.append(_Message(text, mergeable))

    def tick(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self._slots or now < self._next_slot:
            return False
        # A line sent early in a batch can lend its slot to the next waiting
        # packet. Keep the original cadence even when that slot goes unused.
        message = next((item for item in self._slots if not item.sent), None)
        if message is not None:
            self._socket.sendto(chatbox_packet(message.text), self._address)
            message.sent = True
        self._slots.popleft()
        self._next_slot = now + 1.6
        return message is not None
