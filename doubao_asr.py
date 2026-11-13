from __future__ import annotations

import asyncio
import gzip
import json
import os
import struct
import time
import uuid
import wave
from pathlib import Path
from typing import Any

import aiohttp
from settings import path_value, value


ASR_URL = value(
    "DOUBAO_ASR_URL",
    "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
)
RESOURCE_ID = value("DOUBAO_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration")
KEY_FILE = path_value("DOUBAO_ASR_KEY_FILE", "secrets/doubao_asr.key")
ASR_DEBUG_LOG = path_value("DOUBAO_ASR_DEBUG_LOG", "var/asr-debug.log")
SEGMENT_DURATION_MS = 200


class DoubaoAsrError(RuntimeError):
    """A safe, user-facing error from the Doubao ASR client."""


def _debug_log(event: str, **fields: Any) -> None:
    item = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields}
    try:
        ASR_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ASR_DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError:
        pass


def key_available() -> bool:
    try:
        return bool(KEY_FILE.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _read_key() -> str:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DoubaoAsrError("豆包 ASR key 文件不可读。") from exc
    if not key:
        raise DoubaoAsrError("豆包 ASR key 为空。")
    return key


def _read_wav(path: Path) -> bytes:
    try:
        data = path.read_bytes()
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
                or audio.getcomptype() != "NONE"
            ):
                raise DoubaoAsrError("音频不是豆包 ASR 要求的 16kHz、16-bit、单声道 WAV。")
            if audio.getnframes() == 0:
                raise DoubaoAsrError("音频片段为空。")
        return data
    except DoubaoAsrError:
        raise
    except (OSError, wave.Error) as exc:
        raise DoubaoAsrError("音频片段不是有效的 WAV 文件。") from exc


def _pack_frame(
    message_type: int,
    flags: int,
    serialization: int,
    payload: bytes,
    sequence: int,
) -> bytes:
    compressed = gzip.compress(payload)
    header = bytes([0x11, (message_type << 4) | flags, (serialization << 4) | 0x01, 0x00])
    body = bytearray(header)
    if flags & 0x01:
        body.extend(struct.pack(">i", sequence))
    body.extend(struct.pack(">I", len(compressed)))
    body.extend(compressed)
    return bytes(body)


def _parse_response(message: bytes) -> dict[str, Any]:
    if len(message) < 4:
        raise DoubaoAsrError("豆包 ASR 返回了无效的二进制响应。")

    header_size = (message[0] & 0x0F) * 4
    message_type = message[1] >> 4
    flags = message[1] & 0x0F
    serialization = message[2] >> 4
    compression = message[2] & 0x0F
    if header_size < 4 or len(message) < header_size:
        raise DoubaoAsrError("豆包 ASR 返回了无效的响应头。")

    payload = message[header_size:]
    sequence = 0
    if flags & 0x01:
        if len(payload) < 4:
            raise DoubaoAsrError("豆包 ASR 响应缺少序列号。")
        sequence = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]

    event = 0
    if flags & 0x04:
        if len(payload) < 4:
            raise DoubaoAsrError("豆包 ASR 响应缺少事件编号。")
        event = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]

    code = 0
    if message_type == 0x09:
        if len(payload) < 4:
            raise DoubaoAsrError("豆包 ASR 响应缺少负载长度。")
        payload = payload[4:]
    elif message_type == 0x0F:
        if len(payload) < 8:
            raise DoubaoAsrError("豆包 ASR 返回了不完整的错误响应。")
        code = struct.unpack(">i", payload[:4])[0]
        payload = payload[8:]
    else:
        raise DoubaoAsrError(f"豆包 ASR 返回了未知消息类型：{message_type}。")

    if compression == 0x01 and payload:
        try:
            payload = gzip.decompress(payload)
        except OSError as exc:
            raise DoubaoAsrError("豆包 ASR 响应解压失败。") from exc

    payload_msg: Any = None
    if payload and serialization == 0x01:
        try:
            payload_msg = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DoubaoAsrError("豆包 ASR 返回了无法解析的 JSON。") from exc

    return {
        "code": code,
        "event": event,
        "is_last_package": bool(flags & 0x02),
        "payload_sequence": sequence,
        "payload_msg": payload_msg,
    }


def _text_from_response(response: dict[str, Any]) -> str:
    message = response.get("payload_msg")
    if not isinstance(message, dict):
        return ""
    result = message.get("result")
    if not isinstance(result, dict):
        return ""
    text = result.get("text")
    return text.strip() if isinstance(text, str) else ""


async def transcribe_async(
    path: Path,
    *,
    url: str = ASR_URL,
    resource_id: str = RESOURCE_ID,
    segment_duration_ms: int = SEGMENT_DURATION_MS,
    pace_audio: bool = True,
    on_partial: Any | None = None,
) -> str:
    audio = _read_wav(path)
    api_key = _read_key()
    request_id = str(uuid.uuid4())
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
    }
    request_payload = {
        "user": {"uid": "local-meeting-assistant"},
        "audio": {
            "format": "wav",
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "enable_nonstream": True,
        },
    }
    segment_size = 16000 * 2 * segment_duration_ms // 1000
    if segment_size <= 0:
        raise DoubaoAsrError("豆包 ASR 分片时长无效。")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.ws_connect(url, headers=headers, heartbeat=20, receive_timeout=5) as ws:
                _debug_log("ws_connected", request_id=request_id, audio_bytes=len(audio), audio_seconds=round(len(audio) / 32000, 2))
                await ws.send_bytes(
                    _pack_frame(
                        message_type=0x01,
                        flags=0x01,
                        serialization=0x01,
                        payload=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
                        sequence=1,
                    )
                )
                initial = await ws.receive(timeout=15)
                if initial.type != aiohttp.WSMsgType.BINARY:
                    raise DoubaoAsrError("豆包 ASR 建连后没有返回有效响应。")
                initial_response = _parse_response(initial.data)
                _debug_log(
                    "initial_response",
                    request_id=request_id,
                    code=initial_response["code"],
                    asr_event=initial_response["event"],
                    last=initial_response["is_last_package"],
                )
                if initial_response["code"]:
                    raise DoubaoAsrError(f"豆包 ASR 请求失败（错误码 {initial_response['code']}）。")

                async def send_audio() -> None:
                    chunks = [audio[offset : offset + segment_size] for offset in range(0, len(audio), segment_size)]
                    for index, chunk in enumerate(chunks):
                        last = index == len(chunks) - 1
                        sequence = -(index + 2) if last else index + 2
                        await ws.send_bytes(
                            _pack_frame(
                                message_type=0x02,
                                flags=0x03 if last else 0x01,
                                serialization=0x00,
                                payload=chunk,
                                sequence=sequence,
                            )
                        )
                        if pace_audio and not last:
                            await asyncio.sleep(segment_duration_ms / 1000)

                sender = asyncio.create_task(send_audio())
                latest_text = ""
                deadline = time.monotonic() + max(30.0, len(audio) / 32000 + 20.0)
                try:
                    while time.monotonic() < deadline:
                        if sender.done() and sender.exception() is not None:
                            raise sender.exception()  # type: ignore[misc]
                        try:
                            message = await ws.receive(timeout=1)
                        except asyncio.TimeoutError:
                            if sender.done() and time.monotonic() + 1 >= deadline:
                                break
                            continue
                        if message.type == aiohttp.WSMsgType.BINARY:
                            response = _parse_response(message.data)
                            if response["code"]:
                                _debug_log("response_error", request_id=request_id, code=response["code"], asr_event=response["event"])
                                raise DoubaoAsrError(f"豆包 ASR 请求失败（错误码 {response['code']}）。")
                            response_text = _text_from_response(response)
                            payload_msg = response.get("payload_msg")
                            result = payload_msg.get("result") if isinstance(payload_msg, dict) else None
                            utterances = result.get("utterances") if isinstance(result, dict) else None
                            _debug_log(
                                "response",
                                request_id=request_id,
                                code=response["code"],
                                asr_event=response["event"],
                                last=response["is_last_package"],
                                text_chars=len(response_text),
                                utterances=len(utterances) if isinstance(utterances, list) else 0,
                            )
                            if response_text and response_text != latest_text:
                                latest_text = response_text
                                if on_partial is not None:
                                    on_partial(latest_text)
                            if response["is_last_package"]:
                                _debug_log("transcribe_done", request_id=request_id, text_chars=len(latest_text))
                                return latest_text
                        elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                            break
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise DoubaoAsrError("豆包 ASR WebSocket 连接异常。")
                finally:
                    if not sender.done():
                        sender.cancel()
                    try:
                        await sender
                    except asyncio.CancelledError:
                        pass
                raise DoubaoAsrError("豆包 ASR 未返回完整识别结果，请检查网络或 asr-debug.log。")
        except DoubaoAsrError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            raise DoubaoAsrError("豆包 ASR 连接失败，请检查网络或服务配置。") from exc


def transcribe(path: Path, *, pace_audio: bool = True, on_partial: Any | None = None) -> str:
    return asyncio.run(transcribe_async(path, pace_audio=pace_audio, on_partial=on_partial))
