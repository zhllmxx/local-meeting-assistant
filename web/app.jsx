import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal, createRoot } from "react-dom";
import {
  Button,
  Card,
  Col,
  ConfigProvider,
  Empty,
  Input,
  Popconfirm,
  Row,
  Segmented,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CheckOutlined,
  DeleteOutlined,
  EditOutlined,
  SendOutlined,
} from "@ant-design/icons";
import "antd/dist/reset.css";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

async function request(url, body) {
  const response = await fetch(url, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setDot(id, ready) {
  const dot = document.getElementById(id);
  dot?.classList.toggle("ready", Boolean(ready));
  dot?.classList.toggle("error", !ready);
}

function TranscriptRow({ item, onInsert, insertTarget, automatic }) {
  const addTranscript = () => onInsert(item.text, insertTarget);
  return (
    <article className="transcript-entry">
      <div className="transcript-meta">
        <time>{item.time}</time>
      </div>
      <div className="transcript-body">
        {automatic ? <div className="transcript-text-button">{item.text}</div> : <button
          className="transcript-text-button"
          type="button"
          aria-label={`将转写加入 ${insertTarget === "query" ? "Query" : "Answer"}：${item.text}`}
          onClick={addTranscript}
          title={`点击加入 ${insertTarget === "query" ? "Query" : "Answer"}`}
        >
          {item.text}
        </button>}
        {item.audio_url && <audio className="transcript-audio" controls preload="none" src={item.audio_url} aria-label={`播放 ${item.time} 的原始录音`} />}
      </div>
    </article>
  );
}

function TranscriptDropField({ label, value, onChange, placeholder }) {
  return (
    <div className="drop-field-wrap">
      <div className="field-label"><Text strong>{label}</Text><Text type="secondary">可点击转写加入</Text></div>
      <TextArea
        className="transcript-drop-field"
        autoSize={{ minRows: 3, maxRows: 8 }}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

function AnswerResult({ label, result, kind }) {
  const status = { queued: "排队中", answering: "生成中", streaming: "流式输出", answered: "已完成", error: "失败", not_requested: "未运行" }[result.status] || "等待中";
  const active = ["queued", "answering", "streaming"].includes(result.status);
  return (
    <section className={`answer-lane answer-lane-${kind}`} aria-label={label}>
      <div className="answer-lane-heading">
        <Text strong>{label}</Text>
        <Tag color={result.status === "error" ? "red" : result.status === "answered" ? "green" : active ? "blue" : "default"}>{status}</Tag>
      </div>
      {active && <div className="answer-progress">{result.progress || "等待返回…"}</div>}
      <Paragraph className="qa-answer">{result.answer || (result.status === "not_requested" ? "这条历史记录未运行 Agent。" : active ? "" : "暂无内容")}</Paragraph>
      {result.error && <div className="answer-error">{result.error}</div>}
      {kind === "agent" && result.tools?.length > 0 && <div className="tool-trace">{result.tools.slice(-2).map((step, index) => <div key={index}>{step.detail}</div>)}</div>}
      {(result.first_token_ms != null || result.elapsed_ms != null) && <div className="answer-timing">
        {result.first_token_ms != null && `首字 ${(result.first_token_ms / 1000).toFixed(1)}s`}
        {result.elapsed_ms != null && ` · 总计 ${(result.elapsed_ms / 1000).toFixed(1)}s`}
      </div>}
    </section>
  );
}

function QueryHistoryItem({ item, onSave, singleSpeaker }) {
  const api = item.api || { status: item.status, answer: item.answer, error: item.error };
  const agent = item.agent || { status: "not_requested", answer: "" };
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState(item.question || item.query || "");
  const [meetingAnswer, setMeetingAnswer] = useState(item.meeting_answer || "");
  const [answer, setAnswer] = useState(api.answer || "");
  const [agentAnswer, setAgentAnswer] = useState(agent.answer || "");
  const [saving, setSaving] = useState(false);
  const pending = [api, agent].some((result) => ["queued", "answering", "streaming"].includes(result.status));

  useEffect(() => {
    if (!editing) {
      setQuestion(item.question || item.query || "");
      setMeetingAnswer(item.meeting_answer || "");
      setAnswer(api.answer || "");
      setAgentAnswer(agent.answer || "");
    }
  }, [item.id, item.question, item.query, item.meeting_answer, api.answer, agent.answer, editing]);

  const save = async () => {
    setSaving(true);
    try {
      await onSave(item.id, question, meetingAnswer, answer, agent.status === "not_requested" ? undefined : agentAnswer);
      setEditing(false);
    } catch (error) {
      message.error(error.message || String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card size="small" className="qa-card">
      <div className="qa-card-heading">
        <Space size={8}><Text type="secondary">{item.time}</Text><Text type="secondary">{pending ? "双路并行处理中" : "回答已完成"}</Text></Space>
        <Tooltip title={pending ? "回答完成后可编辑" : "编辑这组问答"}>
          <Button size="small" type="text" icon={<EditOutlined />} aria-label="编辑问答" disabled={pending} onClick={() => setEditing(!editing)} />
        </Tooltip>
      </div>
      {editing ? (
        <Space direction="vertical" size={10} className="full-width">
          <div><div className="field-label"><Text strong>{singleSpeaker ? "对方的问题" : "Query"}</Text></div><TextArea autoSize={{ minRows: 2, maxRows: 6 }} value={question} onChange={(event) => setQuestion(event.target.value)} /></div>
          {(!singleSpeaker || meetingAnswer) && <div><div className="field-label"><Text strong>会议 Answer 原话</Text></div><TextArea autoSize={{ minRows: 2, maxRows: 6 }} value={meetingAnswer} onChange={(event) => setMeetingAnswer(event.target.value)} /></div>}
          <div><div className="field-label"><Text strong>API 答案</Text></div><TextArea autoSize={{ minRows: 3, maxRows: 9 }} value={answer} onChange={(event) => setAnswer(event.target.value)} /></div>
          {agent.status !== "not_requested" && <div><div className="field-label"><Text strong>Agent 答案</Text></div><TextArea autoSize={{ minRows: 3, maxRows: 9 }} value={agentAnswer} onChange={(event) => setAgentAnswer(event.target.value)} /></div>}
          <Space><Button type="primary" size="small" icon={<CheckOutlined />} loading={saving} onClick={save}>保存修改</Button><Button size="small" onClick={() => setEditing(false)}>取消</Button></Space>
        </Space>
      ) : (
        <div className="qa-card-content">
          <div className="qa-block"><Text className="qa-label">{singleSpeaker ? "对方的问题" : "Query"}</Text><Paragraph className="qa-question">{item.question || item.query}</Paragraph></div>
          {item.meeting_answer && <div className="qa-block"><Text className="qa-label">会议 Answer 原话</Text><Paragraph className="qa-meeting-answer">{item.meeting_answer}</Paragraph></div>}
          <div className="answer-columns"><AnswerResult label="API 答案" result={api} kind="api" /><AnswerResult label="Agent 答案" result={agent} kind="agent" /></div>
        </div>
      )}
    </Card>
  );
}

function CaptureMonitor({ onQueryUpdate }) {
  const [live, setLive] = useState({
    connected: false,
    capture: "stopped",
    device_name: "",
    rms: 0,
    dbfs: -90,
    segment_seconds: 0,
    segment_state: "idle",
    asr_status: "idle",
    asr_kind: "",
    asr_text: "",
    asr_index: 0,
  });
  const samples = useRef(Array(100).fill(0));
  const canvas = useRef(null);

  useEffect(() => {
    const source = new EventSource("/api/events");
    const eventNames = [
      "snapshot", "meter", "speech_started", "segment_discarded", "asr_queued", "qa_updated",
      "asr_started", "asr_partial", "asr_preview_done", "asr_done", "asr_error",
      "asr_idle", "capture_started", "capture_stopping", "capture_stream_ended", "capture_stopped",
    ];
    const onEvent = (event) => {
      try {
        const next = JSON.parse(event.data);
        if (event.type === "qa_updated") { onQueryUpdate(next); return; }
        if (event.type === "snapshot") {
          samples.current = Array(100).fill(levelFromDbfs(next.dbfs));
        } else if (event.type === "meter") {
          samples.current.push(levelFromDbfs(next.dbfs));
          if (samples.current.length > 100) samples.current.shift();
        }
        setLive((previous) => ({ ...previous, ...next, connected: true }));
      } catch (error) {
        console.error("Invalid capture telemetry event", error);
      }
    };
    for (const name of eventNames) source.addEventListener(name, onEvent);
    source.onerror = () => setLive((previous) => ({ ...previous, connected: false }));
    return () => source.close();
  }, [onQueryUpdate]);

  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext("2d");
    if (!element || !context) return undefined;
    let timer = 0;
    const draw = () => {
      const rect = element.getBoundingClientRect();
      const ratio = Math.max(1, window.devicePixelRatio || 1);
      const width = Math.max(1, Math.round(rect.width * ratio));
      const height = Math.max(1, Math.round(rect.height * ratio));
      if (element.width !== width || element.height !== height) {
        element.width = width;
        element.height = height;
      }
      context.clearRect(0, 0, width, height);
      context.fillStyle = "#f7faf9";
      context.fillRect(0, 0, width, height);
      context.strokeStyle = "#dfe8e5";
      context.lineWidth = ratio;
      context.beginPath();
      context.moveTo(0, height / 2);
      context.lineTo(width, height / 2);
      context.stroke();

      const values = samples.current;
      const center = height / 2;
      const maxHeight = height * 0.42;
      const upper = values.map((value, index) => [
        index * width / Math.max(1, values.length - 1),
        center - Math.max(1.5 * ratio, value * maxHeight),
      ]);
      const lower = values.map((value, index) => [
        index * width / Math.max(1, values.length - 1),
        center + Math.max(1.5 * ratio, value * maxHeight),
      ]).reverse();
      context.beginPath();
      for (let index = 0; index < upper.length; index += 1) {
        const [x, y] = upper[index];
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      for (const [x, y] of lower) context.lineTo(x, y);
      context.closePath();
      context.fillStyle = live.capture === "recording" ? "rgba(23, 107, 103, 0.24)" : "rgba(111, 128, 138, 0.14)";
      context.fill();
      context.strokeStyle = live.capture === "recording" ? "#176b67" : "#829098";
      context.lineWidth = 1.5 * ratio;
      context.beginPath();
      upper.forEach(([x, y], index) => index === 0 ? context.moveTo(x, y) : context.lineTo(x, y));
      context.stroke();
    };
    draw();
    timer = window.setInterval(draw, 80);
    return () => window.clearInterval(timer);
  }, [live.capture]);

  const captureLabel = live.capture !== "recording" ? "未采集"
    : live.segment_state === "collecting" ? "正在采集语音片段"
      : live.segment_state === "asr" ? "音频已送入 ASR"
        : live.segment_state === "queued" || live.segment_state === "preview_queued" ? "音频已进入 ASR 队列"
          : "持续采集中";
  const asrLabels = {
    idle: "等待音频片段",
    queued: "已进入豆包 ASR 队列",
    processing: "音频已送入豆包，正在识别",
    streaming: "豆包正在流式返回文本",
    preview_ready: "实时预览已更新，最终文本待分段结束",
    complete: "最终识别完成",
    error: live.asr_error || "ASR 处理失败",
  };
  const dbfs = Number.isFinite(Number(live.dbfs)) ? Number(live.dbfs).toFixed(1) : "-90.0";

  return (
    <section className="capture-monitor" aria-label="实时音频与 ASR 状态">
      <div className="monitor-head">
        <div className="monitor-title">
          <strong>实时音频</strong>
          <span>{live.device_name || "等待采集设备"}</span>
        </div>
        <div className="monitor-metrics">
          <span className={`monitor-dot ${live.capture === "recording" ? "live" : ""}`} />
          <span>{captureLabel}</span>
          <span className="monitor-reading">RMS {live.rms || 0} · {dbfs} dBFS</span>
        </div>
      </div>
      <canvas ref={canvas} className="monitor-wave" aria-label="最近十秒音频电平波形" />
      <div className="monitor-detail">
        <span className="segment-reading">当前分段 {Number(live.segment_seconds || 0).toFixed(1)} 秒</span>
        <div className="asr-live">
          <div className="asr-live-heading">
            <strong>豆包 ASR</strong>
            <span>{asrLabels[live.asr_status] || "等待音频片段"}</span>
            {live.asr_kind === "preview" && <Tag color="cyan">滚动预览</Tag>}
          </div>
          <div className={`asr-live-text ${live.asr_status === "streaming" ? "streaming" : ""}`}>
            {live.asr_text || "等待音频送入 ASR"}
          </div>
        </div>
        <span className={`event-connection ${live.connected ? "connected" : ""}`} title={live.connected ? "实时状态连接正常" : "正在连接实时状态"} />
      </div>
    </section>
  );
}

function levelFromDbfs(dbfs) {
  const value = Number(dbfs);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, (value + 72) / 48));
}

function MeetingApp() {
  const [state, setState] = useState({
    capture: "stopped", transcript: [], answers: [], queries: [], session_id: null,
    services: { huoshan_llm: false, doubao_asr: false },
  });
  const [question, setQuestion] = useState("");
  const [meetingAnswer, setMeetingAnswer] = useState("");
  const [insertTarget, setInsertTarget] = useState("query");
  const [sending, setSending] = useState(false);
  const [mode, setMode] = useState("speaker_single");
  const [devices, setDevices] = useState([]);
  const [captureBusy, setCaptureBusy] = useState(false);
  const singleSpeaker = mode === "speaker_single";
  const captureActive = state.capture === "recording" || state.capture === "stopping";
  const [messageApi, contextHolder] = message.useMessage();

  const onQueryUpdate = useCallback(({ session_id, query }) => {
    setState((previous) => {
      if (previous.session_id !== session_id || !previous.queries.some((item) => item.id === query.id && item.generation === query.generation)) return previous;
      const queries = previous.queries.map((item) => item.id === query.id && item.generation === query.generation ? query : item);
      return { ...previous, queries, answers: queries };
    });
  }, []);

  const showError = useCallback((error) => {
    const banner = document.getElementById("error-banner");
    if (banner) {
      banner.textContent = error.message || String(error);
      banner.classList.remove("hidden");
    }
    messageApi.error(error.message || String(error));
  }, [messageApi]);

  const refreshState = useCallback(async () => {
    const next = await request("/api/state");
    setState(next);
    const transcriptCount = document.getElementById("transcript-count");
    if (transcriptCount) transcriptCount.textContent = `${next.transcript.length} 段`;
    setDot("llm-dot", next.services.huoshan_llm);
    setDot("asr-dot", next.services.doubao_asr);
    const recording = next.capture === "recording";
    const stopping = next.capture === "stopping";
    if (recording || stopping) setMode(next.capture_mode || "general");
    document.getElementById("audio-dot")?.classList.toggle("ready", recording);
    document.getElementById("audio-dot")?.classList.toggle("error", !recording);
    document.getElementById("capture-indicator")?.classList.toggle("live", recording);
    const title = document.getElementById("capture-title");
    if (title) title.textContent = recording ? "正在采集" : stopping ? "正在收尾转写" : "未开始采集";
    const subtitle = document.getElementById("capture-subtitle");
    if (subtitle) subtitle.textContent = next.session_id
      ? `本地会话 ${next.session_id}${next.live?.device_name ? ` · ${next.live.device_name}` : ""}`
      : "选择采集设备后手动开始";
    const system = document.getElementById("system-device");
    if (system) {
      system.disabled = recording || stopping;
    }
    document.getElementById("start-button")?.classList.toggle("hidden", recording || stopping);
    document.getElementById("stop-button")?.classList.toggle("hidden", !recording);
    const stop = document.getElementById("stop-button");
    if (stop) stop.disabled = stopping;
    if (next.capture_error) showError(new Error(next.capture_error));
  }, [showError]);

  const refreshDevices = useCallback(async () => {
    const result = await request("/api/devices");
    setDevices(result.devices);
  }, []);

  useEffect(() => {
    const available = singleSpeaker ? devices.filter((device) => device.id === "screen" || device.id === "global") : devices;
    const system = document.getElementById("system-device");
    if (system) {
      const previousId = system.value;
      system.replaceChildren(...available.map((device) => new Option(device.name, device.id)));
      const preferred = available.find((device) => captureActive && device.id === state.live?.device_id)
        || available.find((device) => device.id === previousId)
        || available.find((device) => !singleSpeaker && device.name === "MacBook Pro麦克风")
        || available.find((device) => device.id === "screen")
        || available.find((device) => device.id === "global");
      if (preferred) system.value = preferred.id;
      system.disabled = captureActive || captureBusy;
    }
  }, [devices, singleSpeaker, captureActive, captureBusy, state.live?.device_id]);

  useEffect(() => {
    document.getElementById("transcript-insert-controls")?.classList.toggle("hidden", singleSpeaker);
    document.getElementById("transcript-heading").textContent = singleSpeaker ? "对方的实时转写" : "实时转写素材";
    document.getElementById("transcript-helper").textContent = singleSpeaker
      ? "对方停止说话 800ms 后自动提交，每段原声可点击播放。"
      : "先选 Query 或 Answer，再点击任意转写片段即可加入。";
    document.getElementById("assistant-heading").textContent = singleSpeaker ? "实时回答" : "问答编排";
    document.getElementById("assistant-subtitle").textContent = singleSpeaker ? "结合简历、面经与历史对话" : "自动问答，也可人工组合后发送";
  }, [singleSpeaker]);

  useEffect(() => {
    refreshState().catch(showError);
    refreshDevices().catch(showError);
    const timer = window.setInterval(() => refreshState().catch(showError), 1200);
    return () => window.clearInterval(timer);
  }, [refreshState, refreshDevices, showError]);

  useEffect(() => {
    const refreshButton = document.getElementById("refresh-devices");
    const refresh = () => refreshDevices().catch(showError);
    const startButton = document.getElementById("start-button");
    const start = async () => {
      startButton.disabled = true;
      setCaptureBusy(true);
      try {
        await request("/api/capture/start", {
          system_device: document.getElementById("system-device")?.value,
          include_mic: false,
          mode,
        });
        document.getElementById("error-banner")?.classList.add("hidden");
        await refreshState();
      } catch (error) { showError(error); }
      finally { startButton.disabled = false; setCaptureBusy(false); }
    };
    const stopButton = document.getElementById("stop-button");
    const stop = async () => {
      stopButton.disabled = true;
      try { await request("/api/capture/stop", {}); await refreshState(); }
      catch (error) { showError(error); }
      finally { stopButton.disabled = false; }
    };
    refreshButton?.addEventListener("click", refresh);
    startButton?.addEventListener("click", start);
    stopButton?.addEventListener("click", stop);
    return () => {
      refreshButton?.removeEventListener("click", refresh);
      startButton?.removeEventListener("click", start);
      stopButton?.removeEventListener("click", stop);
    };
  }, [refreshState, refreshDevices, showError, mode]);

  const insertTranscript = (text, destination) => {
    if (destination === "query") setQuestion((value) => value ? `${value}\n${text}` : text);
    else setMeetingAnswer((value) => value ? `${value}\n${text}` : text);
    messageApi.success(`已放入 ${destination === "query" ? "Query" : "Answer"}`);
  };

  const saveQuery = async (id, editedQuestion, editedMeetingAnswer, answer, agentAnswer) => {
    await request("/api/queries/update", {
      id, question: editedQuestion, meeting_answer: editedMeetingAnswer, answer, agent_answer: agentAnswer,
    });
    await refreshState();
    messageApi.success("问答已保存");
  };

  const submitQuery = async (event) => {
    event.preventDefault();
    if (!question.trim()) {
      messageApi.warning("先把 Query 片段放到问题框里。");
      return;
    }
    setSending(true);
    try {
      await request("/api/ask", { question: question.trim(), meeting_answer: meetingAnswer.trim() });
      setQuestion("");
      setMeetingAnswer("");
      await refreshState();
      messageApi.success("已提交，问答按顺序生成");
    } catch (error) { showError(error); }
    finally { setSending(false); }
  };

  const clearQueries = async () => {
    try {
      const result = await request("/api/queries/clear", {});
      setQuestion("");
      setMeetingAnswer("");
      await refreshState();
      messageApi.success(`已清空 ${result.cleared} 组问答`);
    } catch (error) { showError(error); }
  };

  const copyTranscript = async () => {
    const text = [...state.transcript].reverse().map((item) => `${item.time} ${item.text}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      messageApi.success("已复制转写");
    } catch (error) { showError(error); }
  };

  useEffect(() => {
    const button = document.getElementById("copy-transcript");
    button?.addEventListener("click", copyTranscript);
    return () => button?.removeEventListener("click", copyTranscript);
  }, [copyTranscript]);

  const transcript = [...(state.transcript || [])].reverse().map((item) => ({
    ...item,
    audio_url: item.audio_url || (state.session_id && item.utterance
      ? `/api/audio/${encodeURIComponent(state.session_id)}/${item.utterance}`
      : ""),
  }));
  const queries = [...(state.queries || state.answers || [])].reverse();

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#176b67", borderRadius: 5, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" } }}>
      {contextHolder}
      {createPortal(
        <div className="capture-mode-bar">
          <Segmented aria-label="工作台模式" value={mode} onChange={setMode} disabled={captureActive || captureBusy}
            options={[{ label: "扬声器单人", value: "speaker_single" }, { label: "通用采集", value: "general" }]} />
          <span className="mode-description">{singleSpeaker ? "对方一人发言 · 800ms 静音自动提问 · 每问一答" : "选择音频输入 · 自动问答 · 支持手动编排"}</span>
        </div>, document.getElementById("capture-mode-root"),
      )}
      {createPortal(<CaptureMonitor onQueryUpdate={onQueryUpdate} />, document.getElementById("telemetry-root"))}
      {createPortal(
        <div className="transcript-react-list">
          {transcript.length
            ? transcript.map((item, index) => (
                <TranscriptRow key={`${item.time}-${index}`} item={item} onInsert={insertTranscript} insertTarget={insertTarget} automatic={singleSpeaker} />
              ))
            : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="开始采集后，转写片段会显示在这里。" />}
        </div>,
        document.getElementById("transcript-list"),
      )}
      {createPortal(
        <Segmented
          size="small"
          value={insertTarget}
          onChange={setInsertTarget}
          options={[{ label: "Query", value: "query" }, { label: "Answer", value: "answer" }]}
        />,
        document.getElementById("insert-target-root"),
      )}
      <section className={`composer${singleSpeaker ? " composer-automatic" : ""}`}>
        <div className="compose-heading">
          <div><Text strong>{singleSpeaker ? "已开启自动问答" : "自动问答"}</Text><Text type="secondary">{singleSpeaker ? "豆包 2.1 Pro · Thinking 已关闭" : "每段采集语音在 800ms 静音后自动生成"}</Text></div>
          <Popconfirm title="清空全部问答历史？" description="转写素材会保留；清空后，旧问答不会再进入后续 LLM 请求。" okText="清空" cancelText="取消" onConfirm={clearQueries}>
            <Button danger type="text" icon={<DeleteOutlined />}>清空问答</Button>
          </Popconfirm>
        </div>
        {singleSpeaker ? <div className="automatic-note">每题同时生成 API 答案和 Agent 答案，独立排队、流式展示；新问题不会中断已有回答。</div> : <form onSubmit={submitQuery}>
          <Row gutter={[12, 10]}>
            <Col xs={24} xl={12}>
              <TranscriptDropField label="Query / 问题" value={question} onChange={setQuestion} placeholder="点击左侧转写片段加入，或直接输入。" />
            </Col>
            <Col xs={24} xl={12}>
              <TranscriptDropField label="Answer / 会议原话" value={meetingAnswer} onChange={setMeetingAnswer} placeholder="切换到 Answer 后，点击左侧转写片段加入。" />
            </Col>
            <Col span={24}>
              <div className="submit-row">
                <Text type="secondary">每题双路并行生成；两条路线各自排队，不互相等待。</Text>
                <Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={sending}>生成回答</Button>
              </div>
            </Col>
          </Row>
        </form>}
      </section>
      <div className="history-heading">
        <Text strong>问答历史</Text>
        <Tag>{queries.length} 组</Tag>
      </div>
      <div className="history-list" aria-live="polite">
        {queries.length
          ? queries.map((item) => <QueryHistoryItem key={`${item.generation}-${item.id}`} item={item} onSave={saveQuery} singleSpeaker={singleSpeaker} />)
          : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={singleSpeaker ? "开始采集后，对方说话就会自动生成问答。" : "还没有提交问答。"} />}
      </div>
    </ConfigProvider>
  );
}

const root = createRoot(document.getElementById("editor-root"));
root.render(<MeetingApp />);
