import io
import json
import queue
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class StopWorker(BaseException):
    pass


class FiniteQueue(queue.Queue):
    def get(self, *args, **kwargs):
        if self.empty():
            raise StopWorker()
        return super().get(*args, **kwargs)


class SpeakerModeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runs = Path(self.directory.name)
        for name, value in (
            ("RUNS", self.runs), ("SESSION_DATA", {}),
            ("STATE", {"session_id": None, "capture": "stopped", "capture_mode": "general"}),
            ("QUERY_QUEUE", FiniteQueue()),
            ("AGENT_QUERY_QUEUE", FiniteQueue()),
        ):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("debug_log", "publish_live_event", "publish_query_event", "ensure_query_worker"):
            patcher = patch.object(app, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        config = patch.object(app, "load_huoshan_config", return_value=("https://test/v1/chat/completions", "test"))
        config.start()
        self.addCleanup(config.stop)

    def test_single_speaker_rejects_microphones_and_mixed_inputs(self):
        for device, microphone in (("avfoundation:MacBook Pro麦克风", None), ("screen", "avfoundation:mic")):
            with self.subTest(device=device, microphone=microphone), self.assertRaises(ValueError):
                app.start_capture(device, microphone, "speaker_single")
        with self.assertRaises(ValueError):
            app.start_capture("screen", None, "unknown")

    def test_native_screen_route_is_listed_without_ffmpeg(self):
        with patch.object(app, "FFMPEG", str(self.runs / "missing-ffmpeg")):
            devices = app.list_audio_devices()
        self.assertIn(app.SCREEN_AUDIO_ID, {item["id"] for item in devices})

    def test_transcription_uses_only_doubao_with_partial_updates(self):
        callback = Mock()
        path = Path("speech.wav")
        with patch.object(app.doubao_asr, "transcribe", return_value="你好") as transcribe:
            self.assertEqual(app.transcribe(path, callback), "你好")
        transcribe.assert_called_once_with(path, pace_audio=False, on_partial=callback)

    def test_session_mode_survives_restore_and_legacy_sessions_still_load(self):
        folder = self.runs / "20261113-190000"
        folder.mkdir()
        metadata = folder / "session.json"
        metadata.write_text(json.dumps({"capture_mode": "speaker_single"}))
        app.restore_latest_session()
        self.assertEqual(app.STATE["capture_mode"], "speaker_single")
        self.assertEqual(app.SESSION_DATA[folder.name]["capture_mode"], "speaker_single")
        metadata.unlink()
        app.restore_latest_session()
        self.assertEqual(app.STATE["capture_mode"], "general")

    def cut_audio(self, pause_frames):
        speech = struct.pack("<320h", *([2500, -2500] * 160))
        silence = bytes(app.PCM_FRAME_BYTES)
        pcm = speech * 20 + silence * pause_frames + speech * 20 + silence * 40
        items = queue.Queue()
        process = Mock(stdout=io.BytesIO(pcm))
        app.capture_worker(self.runs / "vad", process, threading.Event(), items)
        results = []
        while not items.empty():
            item = items.get_nowait()
            if item and item["kind"] == "final":
                results.append(item)
        return results

    def test_pause_below_800ms_stays_in_one_query(self):
        self.assertEqual(len(self.cut_audio(39)), 1)

    def test_800ms_silence_creates_two_queries(self):
        self.assertEqual(len(self.cut_audio(40)), 2)

    def test_new_query_keeps_inflight_answer_and_inherits_history(self):
        session_id = "20261113-190001"
        session = {
            "capture_mode": "speaker_single", "transcript": [], "queries": [], "answers": [],
            "history_generation": 0, "transcript_baseline": 0,
        }
        app.SESSION_DATA[session_id] = session
        app.STATE["session_id"] = session_id
        requests = []

        def answer(messages, on_partial=None):
            requests.append(messages)
            self.assertIn("扬声器单人模式", messages[0]["content"])
            if len(requests) == 1:
                app.enqueue_query("第二个追问", session_id, source="audio")
                self.assertEqual(session["queries"][0]["status"], "answering")
                return "第一题的完整回答"
            self.assertIn({"role": "assistant", "content": "第一题的完整回答"}, messages)
            return "第二题的完整回答"

        with patch.object(app.KNOWLEDGE_BASE, "retrieve", return_value="测试简历材料"), \
                patch.object(app, "call_huoshan_llm", side_effect=answer):
            app.enqueue_query("第一个问题", session_id, source="audio")
            with self.assertRaises(StopWorker):
                app.query_worker()
        self.assertEqual([item["api"]["status"] for item in session["queries"]], ["answered", "answered"])
        with patch.object(app.KNOWLEDGE_BASE, "retrieve", return_value="测试简历材料"), patch.object(app, "call_agent", return_value="资料回答"):
            with self.assertRaises(StopWorker):
                app.query_worker("agent")
        self.assertEqual([item["status"] for item in session["queries"]], ["answered", "answered"])
        self.assertEqual(len(requests), 2)

        app.clear_queries(session_id)
        with patch.object(app.KNOWLEDGE_BASE, "retrieve", return_value="测试简历材料"):
            messages = app.build_plan_messages(session_id, "new", "新问题", "")
        self.assertEqual(len(messages), 2)
        self.assertNotIn("第一题的完整回答", json.dumps(messages, ensure_ascii=False))

    def test_preview_does_not_create_duplicate_queries(self):
        folder = self.runs / "20261113-190002"
        folder.mkdir()
        items = queue.Queue()
        for kind in ("preview", "final"):
            items.put({"kind": kind, "index": 1, "pcm": bytes(3200), "queued_at": 0, "generation": 0})
        items.put(None)
        with patch.object(app, "transcribe", return_value="对方的问题"), patch.object(app, "enqueue_query") as enqueue:
            app.asr_worker(folder, items)
        enqueue.assert_called_once_with("对方的问题", folder.name, source="audio", expected_generation=0)


if __name__ == "__main__":
    unittest.main()
