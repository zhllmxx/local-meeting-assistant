import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import local_agent
import test_speaker_mode as fixtures


class DualAnswerTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.session_id = "20261113-220000"
        for name, value in (
            ("RUNS", self.root), ("SESSION_DATA", {}),
            ("STATE", {"session_id": self.session_id, "capture": "stopped", "capture_mode": "speaker_single"}),
            ("QUERY_QUEUE", fixtures.FiniteQueue()), ("AGENT_QUERY_QUEUE", fixtures.FiniteQueue()),
        ):
            self.stack.enter_context(patch.object(app, name, value))
        for name in ("debug_log", "publish_live_event", "publish_query_event", "ensure_query_worker"):
            self.stack.enter_context(patch.object(app, name))
        self.stack.enter_context(patch.object(app.KNOWLEDGE_BASE, "retrieve", return_value="测试资料"))
        self.stack.enter_context(patch.object(app, "load_huoshan_config", return_value=("https://test/v1/chat/completions", "test")))

    def worker(self, lane):
        try:
            app.query_worker(lane)
        except fixtures.StopWorker:
            pass

    def test_fast_queue_continues_while_agent_is_blocked(self):
        started, release, fast_done = threading.Event(), threading.Event(), threading.Event()
        api_calls, agent_calls = [], []
        def direct(messages, on_partial):
            self.assertTrue(started.wait(2))
            api_calls.append(messages)
            on_partial("API首字")
            if len(api_calls) == 2:
                self.assertIn({"role": "assistant", "content": "快答1"}, messages)
                fast_done.set()
            return f"快答{len(api_calls)}"
        def agent(messages, **kwargs):
            agent_calls.append(messages)
            started.set()
            self.assertTrue(release.wait(3))
            if len(agent_calls) == 2:
                self.assertIn({"role": "assistant", "content": "慢答1"}, messages)
            return f"慢答{len(agent_calls)}"
        app.enqueue_query("第一题")
        app.enqueue_query("第二题")
        with patch.object(app, "call_huoshan_llm", side_effect=direct), patch.object(app, "call_agent", side_effect=agent):
            threads = [threading.Thread(target=self.worker, args=(lane,)) for lane in ("api", "agent")]
            for thread in threads:
                thread.start()
            try:
                self.assertTrue(fast_done.wait(2), "Fast route waited for the slow agent")
                # Wait for the second API result to be committed.
                app.QUERY_QUEUE.join()
                queries = app.SESSION_DATA[self.session_id]["queries"]
                self.assertEqual([query["api"]["status"] for query in queries], ["answered", "answered"])
                self.assertEqual(queries[0]["agent"]["status"], "answering")
            finally:
                release.set()
                for thread in threads:
                    thread.join(4)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([query["agent"]["answer"] for query in queries], ["慢答1", "慢答2"])
        app.restore_latest_session()
        restored = app.STATE["queries"]
        self.assertEqual(restored[1]["api"]["answer"], "快答2")
        self.assertEqual(restored[1]["agent"]["answer"], "慢答2")

    def test_agent_failure_preserves_api_answer(self):
        app.enqueue_query("业务问题")
        with patch.object(app, "call_huoshan_llm", return_value="可先使用的回答"), patch.object(app, "call_agent", side_effect=RuntimeError("Agent出错")):
            self.worker("api")
            self.worker("agent")
        query = app.STATE["queries"][0]
        self.assertEqual(query["api"]["answer"], "可先使用的回答")
        self.assertEqual(query["api"]["status"], "answered")
        self.assertEqual(query["agent"]["status"], "error")

    def test_api_failure_keeps_partial_text_and_agent_answer(self):
        def direct(messages, on_partial):
            on_partial("已收到的API内容")
            raise RuntimeError("连接中断")
        app.enqueue_query("业务问题")
        with patch.object(app, "call_huoshan_llm", side_effect=direct), patch.object(app, "call_agent", return_value="核实后的Agent答案"):
            self.worker("api")
            self.worker("agent")
        query = app.STATE["queries"][0]
        self.assertEqual(query["api"]["status"], "error")
        self.assertEqual(query["api"]["answer"], "已收到的API内容")
        self.assertEqual(query["agent"]["status"], "answered")

    def test_edit_both_answers_survives_restart_and_enters_each_history(self):
        item = app.enqueue_query("问题")
        with patch.object(app, "call_huoshan_llm", return_value="API原答案"), patch.object(app, "call_agent", return_value="Agent原答案"):
            self.worker("api")
            self.worker("agent")
        app.update_query(item["id"], question="修改的问题", answer="API修改答案", agent_answer="Agent修改答案")
        app.restore_latest_session()
        for lane, answer in (("api", "API修改答案"), ("agent", "Agent修改答案")):
            messages = app.build_plan_messages(self.session_id, "next", "追问", "", lane=lane)
            self.assertIn({"role": "assistant", "content": answer}, messages)
            self.assertIn({"role": "user", "content": "修改的问题"}, messages)

    def test_clear_discards_old_stream_and_both_old_histories(self):
        calls = []
        def direct(messages, on_partial):
            calls.append(messages)
            if len(calls) == 1:
                app.clear_queries()
                app.enqueue_query("NEW_QUESTION")
                on_partial("OLD_PARTIAL")
                return "OLD_ANSWER"
            self.assertNotIn("OLD_QUESTION", json.dumps(messages))
            return "新API答案"
        app.enqueue_query("OLD_QUESTION")
        with patch.object(app, "call_huoshan_llm", side_effect=direct), patch.object(app, "call_agent", return_value="新Agent答案") as agent:
            self.worker("api")
            self.worker("agent")
        self.assertEqual(len(app.STATE["queries"]), 1)
        self.assertEqual(app.STATE["queries"][0]["question"], "NEW_QUESTION")
        self.assertNotIn("OLD_", (self.root / self.session_id / "qa.jsonl").read_text())
        self.assertNotIn("OLD_QUESTION", json.dumps(agent.call_args.args[0]))

    def test_direct_stream_disables_thinking_and_emits_partial_text(self):
        chunks = ["data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n" for text in ("你", "好")]
        response = io.BytesIO(("".join(chunks) + "data: [DONE]\n\n").encode())
        partials = []
        with patch.object(app, "load_huoshan_config", return_value=("https://test/v1/chat/completions", "test")), patch.object(app.urllib.request, "urlopen", return_value=response) as request:
            answer = app.call_huoshan_llm([{"role": "user", "content": "你好"}], on_partial=partials.append)
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertTrue(payload["stream"])
        self.assertEqual(answer, "你好")
        self.assertEqual(partials, ["你", "你好"])

    def test_tools_read_fresh_files_and_block_private_or_escaped_paths(self):
        docs = self.root / "docs"
        docs.mkdir()
        path = docs / "flow.md"
        path.write_text("first version\n")
        tools = local_agent.WorkspaceTools(self.root)
        self.assertIn("first version", tools.read_file("docs/flow.md"))
        path.write_text("second version\n")
        self.assertIn("second version", tools.read_file("docs/flow.md"))
        private = self.root / "secrets"
        private.mkdir()
        (private / "private.txt").write_text("PRIVATE")
        (docs / "escape.md").symlink_to(private / "private.txt")
        for name in ("../private.txt", "secrets/private.txt", "docs/escape.md", str(path)):
            self.assertNotIn("PRIVATE", tools.read_file(name))
        self.assertIn("docs/flow.md:1:second version", tools.search_files("second"))
        with patch.object(local_agent.shutil, "which", return_value=None):
            self.assertIn("docs/flow.md:1:second version", tools.search_files("second"))

    def test_real_pydantic_loop_reads_file_and_disables_thinking(self):
        import httpx2 as httpx
        from openai import AsyncOpenAI
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "flow.md").write_text("verified local fact\n")
        requests = []
        def transport(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(body["thinking"], {"type": "disabled"})
            if len(requests) == 1:
                delta = {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"docs/flow.md"}'}}]}
                finish = "tool_calls"
            else:
                self.assertIn("verified local fact", json.dumps(body["messages"]))
                delta, finish = {"content": "根据 docs/flow.md:L1，文件已核实。"}, "stop"
            event = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "test", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            end = {**event, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
            text = "data: " + json.dumps(event) + "\n\ndata: " + json.dumps(end) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=text.encode())
        def client(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        tools, partials = [], []
        with patch("openai.AsyncOpenAI", side_effect=client):
            answer = local_agent.call_agent([{"role": "system", "content": "测试规则"}, {"role": "user", "content": "读取资料"}],
                                           root=self.root, endpoint="https://test/v1/chat/completions", api_key="test", model="test",
                                           on_partial=partials.append, on_tool=lambda **step: tools.append(step))
        self.assertEqual(len(requests), 2)
        self.assertTrue(tools and tools[0]["tool"] == "read_file")
        self.assertTrue(partials)
        self.assertIn("docs/flow.md:L1", answer)
