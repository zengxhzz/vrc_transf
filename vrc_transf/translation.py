import base64
import json
import re
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import Event
from typing import Literal, Protocol

from websockets.exceptions import InvalidStatus
from websockets.sync.client import ClientConnection, connect

from .audio import SAMPLE_RATE, AudioSource

MODEL = "qwen3.8-livetranslate-flash-realtime"
QIANWEN_CN = "qianwen-cn"
MODEL_STUDIO_REGIONS = ("cn-beijing", "ap-southeast-1")


@dataclass(frozen=True)
class TranslationEvent:
    kind: Literal["ready", "partial", "final", "discard"]
    text: str = ""


class Translator(Protocol):
    def stream(
        self, target: str, source: AudioSource | None, stop: Event
    ) -> Iterator[TranslationEvent]: ...


@dataclass(frozen=True)
class QwenSettings:
    api_key: str = field(repr=False)
    workspace: str
    region: str

    def __post_init__(self):
        if not self.api_key.strip():
            raise ValueError("请输入 API Key，或使用演示模式")
        if self.region == QIANWEN_CN:
            return
        if self.region not in MODEL_STUDIO_REGIONS:
            raise ValueError("请选择有效的 API 接入")
        if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", self.workspace):
            raise ValueError("请输入百炼 Workspace ID（地域对应的工作空间标识）")

    @property
    def url(self) -> str:
        host = "maas.qianwenaiapi.com" if self.region == QIANWEN_CN else (
            f"{self.workspace}.{self.region}.maas.aliyuncs.com"
        )
        return f"wss://{host}/api-ws/v1/realtime?model={MODEL}"

    def session_update(self, target: str) -> dict:
        return {
            "type": "session.update",
            "session": {
                "input_modalities": ["audio"],
                "output_modalities": ["text"],
                "audio": {"input": {"format": {"type": "pcm", "sample_rate": SAMPLE_RATE}}},
                "translation": {"language": target},
            },
        }


def audio_event(data: bytes) -> str:
    return json.dumps({
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(data).decode("ascii"),
    })


class QwenEvents:
    def __init__(self):
        self._texts: dict[str, str] = {}
        self._finished: deque[str] = deque(maxlen=64)

    def feed(self, event: dict) -> TranslationEvent | None:
        kind = event.get("type")
        if kind in ("response.text.delta", "response.text.done"):
            response_id = event["response_id"]
            if response_id in self._finished:
                return None
            if kind == "response.text.done":
                self._texts[response_id] = event["text"]
                return None
            text = self._texts.get(response_id, "") + event["delta"]
            self._texts[response_id] = text
            return TranslationEvent("partial", text)

        if kind == "response.done":
            response = event["response"]
            response_id = response["id"]
            if response_id in self._finished:
                return None
            self._finished.append(response_id)
            text = self._texts.pop(response_id, "").strip()
            if response.get("status") == "completed" and text:
                return TranslationEvent("final", text)
            return TranslationEvent("discard")
        return None


def _receive(connection: ClientConnection, timeout: float) -> dict:
    event = json.loads(connection.recv(timeout=timeout))
    if event.get("type") == "error":
        error = event.get("error", {})
        raise RuntimeError(error.get("message") or "实时翻译 API 返回错误")
    return event


def _wait_for(connection: ClientConnection, kind: str, stop: Event) -> bool:
    deadline = time.monotonic() + 6
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            if _receive(connection, 0.1).get("type") == kind:
                return True
        except TimeoutError:
            continue
    if not stop.is_set():
        raise RuntimeError("实时翻译会话初始化超时")
    return False


class QwenTranslator:
    def __init__(self, settings: QwenSettings):
        self.settings = settings

    def stream(self, target: str, source: AudioSource | None, stop: Event) -> Iterator[TranslationEvent]:
        if stop.is_set():
            return
        if source is None:
            raise ValueError("翻译会话缺少音频输入")
        try:
            with connect(
                self.settings.url,
                additional_headers={"Authorization": f"Bearer {self.settings.api_key}"},
                open_timeout=7, close_timeout=1,
            ) as connection:
                yield from self._exchange(connection, target, source, stop)
        except InvalidStatus as error:
            code = error.response.status_code
            config = "API Key 和接入方式" if self.settings.region == QIANWEN_CN else "API Key、工作空间和地域"
            raise RuntimeError(f"翻译 API 连接失败（HTTP {code}），请检查{config}") from error

    def _exchange(self, connection, target, source, stop):
        if not _wait_for(connection, "session.created", stop):
            return
        connection.send(json.dumps(self.settings.session_update(target)))
        if not _wait_for(connection, "session.updated", stop):
            return

        events = QwenEvents()
        with source() as frames:
            yield TranslationEvent("ready")
            next_silence = time.monotonic() + 0.12
            while not stop.is_set():
                pcm = frames.read()
                now = time.monotonic()
                if pcm:
                    connection.send(audio_event(pcm))
                    next_silence = now + 0.12
                elif now >= next_silence:
                    # Process loopback may stop emitting buffers when playback is idle.
                    connection.send(audio_event(b"\0" * (SAMPLE_RATE // 25 * 2)))
                    next_silence = now + 0.04
                try:
                    update = events.feed(_receive(connection, 0.02))
                except TimeoutError:
                    continue
                if update is not None:
                    yield update
            tail = frames.read() + frames.finish()
        if tail:
            connection.send(audio_event(tail))
        connection.send('{"type":"session.finish"}')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                event = _receive(connection, 0.1)
            except TimeoutError:
                continue
            if event.get("type") == "session.finished":
                return
            update = events.feed(event)
            if update is not None:
                yield update


class DemoTranslator:
    def stream(self, target: str, source: AudioSource | None, stop: Event) -> Iterator[TranslationEvent]:
        examples = {
            "zh": ("要不要一起去", "要不要一起去下一个世界？"),
            "en": ("Do you want to", "Do you want to visit the next world together?"),
            "ja": ("一緒に次の", "一緒に次のワールドに行きませんか？"),
            "ko": ("같이 다음", "같이 다음 월드에 갈까요?"),
        }
        partial, final = examples[target]
        yield TranslationEvent("ready")
        if not stop.wait(0.28):
            yield TranslationEvent("partial", partial)
        if not stop.wait(0.42):
            yield TranslationEvent("final", final)
