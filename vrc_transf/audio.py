import csv
import io
import subprocess
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from queue import Empty, Full, Queue

import numpy as np
import soxr

SAMPLE_RATE = 16000


class PcmConverter:
    def __init__(self, rate: int, channels: int, fmt: str = "int16"):
        self.channels = channels
        self.dtype = np.dtype("<f4" if fmt == "float32" else "<i2")
        self.resampler = None
        if rate != SAMPLE_RATE:
            self.resampler = soxr.ResampleStream(rate, SAMPLE_RATE, 1, dtype="float32", quality="LQ")

    def convert(self, data: bytes) -> bytes:
        samples = np.frombuffer(data, dtype=self.dtype).reshape(-1, self.channels)
        if self.dtype.kind == "i" and self.channels == 1 and self.resampler is None:
            return data
        mono = samples.mean(axis=1, dtype=np.float32)
        if self.dtype.kind == "f":
            mono *= 32768
        if self.resampler is not None:
            mono = self.resampler.resample_chunk(mono)
        return self._pcm(mono)

    def finish(self) -> bytes:
        if self.resampler is None:
            return b""
        return self._pcm(self.resampler.resample_chunk(np.empty(0, np.float32), last=True))

    @staticmethod
    def _pcm(samples: np.ndarray) -> bytes:
        return np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes()


class AudioFrames:
    def __init__(self):
        self.queue: Queue[bytes] = Queue(maxsize=64)
        self.converter: PcmConverter
        self.error: BaseException | None = None

    def push(self, data: bytes):
        if not data:
            return
        try:
            self.queue.put_nowait(data)
        except Full:
            # Prefer current audio when a temporary network stall fills the buffer.
            try:
                self.queue.get_nowait()
            except Empty:
                pass
            self.queue.put_nowait(data)

    def read(self) -> bytes:
        if self.error is not None:
            raise RuntimeError(str(self.error)) from self.error
        chunks = []
        for _ in range(12):
            try:
                chunks.append(self.queue.get_nowait())
            except Empty:
                break
        return self.converter.convert(b"".join(chunks)) if chunks else b""

    def finish(self) -> bytes:
        return self.converter.finish()

    def fail(self, error: BaseException):
        self.error = error


AudioSource = Callable[[], AbstractContextManager[AudioFrames]]


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    channels: int
    rate: int
    is_default: bool = False


def scan_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    import pyaudiowpatch as pa

    with pa.PyAudio() as audio:
        try:
            wasapi = audio.get_host_api_info_by_type(pa.paWASAPI)
        except OSError as error:
            raise RuntimeError("找不到 Windows WASAPI 音频设备") from error
        try:
            default_loopback = audio.get_default_wasapi_loopback()["index"]
        except (OSError, RuntimeError):
            default_loopback = -1

        microphones = []
        outputs = []
        for device in audio.get_device_info_generator():
            if device["hostApi"] != wasapi["index"] or not device["maxInputChannels"]:
                continue
            is_loopback = device["isLoopbackDevice"]
            default = default_loopback if is_loopback else wasapi["defaultInputDevice"]
            entry = AudioDevice(
                device["index"], device["name"], int(device["maxInputChannels"]),
                int(device["defaultSampleRate"]), device["index"] == default,
            )
            (outputs if is_loopback else microphones).append(entry)
        return microphones, outputs


@contextmanager
def capture_device(device: AudioDevice):
    import pyaudiowpatch as pa

    frames = AudioFrames()
    frames.converter = PcmConverter(device.rate, device.channels)

    def on_audio(data, _frame_count, _time_info, _status_flags):
        frames.push(data)
        return None, pa.paContinue

    with pa.PyAudio() as audio:
        stream = audio.open(
            format=pa.paInt16, channels=device.channels, rate=device.rate, input=True,
            input_device_index=device.index, frames_per_buffer=device.rate // 25,
            stream_callback=on_audio,
        )
        try:
            yield frames
        finally:
            stream.close()


def vrchat_pid() -> int:
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq VRChat.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", check=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.SubprocessError as error:
        raise RuntimeError("无法检查 VRChat 进程") from error
    pids = [int(row[1]) for row in csv.reader(io.StringIO(result.stdout))
            if len(row) >= 2 and row[0].lower() == "vrchat.exe" and row[1].isdigit()]
    if not pids:
        raise RuntimeError("找不到 VRChat.exe，请先启动 Windows 版 VRChat")
    if len(pids) != 1:
        raise RuntimeError("检测到多个 VRChat 进程，请关闭多余实例或选择指定播放设备")
    return pids[0]


def supports_process_capture() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build >= 20348


@contextmanager
def capture_process(pid: int):
    from capturekit import ProcessAudioSource
    # The pinned capturekit release exposes raw PCM in its Windows backend.
    from capturekit._backends.windows.api import open_audio

    if not supports_process_capture():
        raise RuntimeError("当前 Windows 版本不支持按进程采集，请选择播放设备")
    frames = AudioFrames()
    tap = open_audio(ProcessAudioSource(pid), 48000, channels=2)
    frames.converter = PcmConverter(tap.sample_rate, tap.channels, "float32")
    tap.start(lambda packet: frames.push(packet.data.tobytes()), frames.fail)
    try:
        yield frames
    finally:
        tap.stop()
