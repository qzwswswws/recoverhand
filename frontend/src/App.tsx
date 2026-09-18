import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type {
  ConnectionProfile,
  DeviceEntries,
  DeviceEntry,
  DeviceKind,
  DeviceSlot,
  DeviceState,
  DriverInfo,
  FieldSchema,
  PreviewData,
} from "./types";

const KINDS: DeviceKind[] = ["eeg", "emg", "glove"];
const LABELS: Record<DeviceKind, { title: string; eyebrow: string; index: string }> = {
  eeg: { title: "脑电意图设备", eyebrow: "EEG · 运动想象", index: "01" },
  emg: { title: "腕部肌电贴片", eyebrow: "sEMG · 单个双电极", index: "02" },
  glove: { title: "辅助屈伸手套", eyebrow: "ESP32 · 执行与反馈", index: "03" },
};

const EMPTY_ENTRIES: DeviceEntries = {
  eeg: { driver_id: "", config: {} },
  emg: { driver_id: "", config: {} },
  glove: { driver_id: "", config: {} },
};

const EMPTY_HEALTH = {
  transport_ok: false,
  stream_ok: false,
  time_sync_ok: false,
  signal_ok: false,
  control_ready: false,
  reason: "尚未连接",
};

const EMPTY_STATE: DeviceState = {
  settings_locked: false,
  devices: {
    eeg: { kind: "eeg", driver_id: null, state: "unconfigured", config: {}, health: EMPTY_HEALTH, discovered: [] },
    emg: { kind: "emg", driver_id: null, state: "unconfigured", config: {}, health: EMPTY_HEALTH, discovered: [] },
    glove: { kind: "glove", driver_id: null, state: "unconfigured", config: {}, health: EMPTY_HEALTH, discovered: [] },
  },
};

function defaults(driver: DriverInfo): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(driver.config_schema.properties).map(([key, field]) => [key, field.default ?? ""]),
  );
}

function initialEntries(drivers: DriverInfo[]): DeviceEntries {
  return Object.fromEntries(
    KINDS.map((kind) => {
      const driver = drivers.find((candidate) => candidate.kind === kind && candidate.available);
      return [kind, driver ? { driver_id: driver.id, config: defaults(driver) } : { driver_id: "", config: {} }];
    }),
  ) as DeviceEntries;
}

function stateLabel(state: string): string {
  return (
    {
      unconfigured: "未配置",
      discovering: "正在发现",
      discovered: "已发现",
      connecting: "正在检查",
      connected: "已连接",
      data_valid: "数据有效",
      degraded: "连接降级",
      reconnecting: "正在重连",
      fault: "需要处理",
      disconnected: "已断开",
    }[state] ?? state
  );
}

function stateTone(state: string): string {
  if (state === "data_valid" || state === "connected") return "good";
  if (["fault", "degraded"].includes(state)) return "bad";
  if (["discovering", "connecting", "reconnecting"].includes(state)) return "working";
  return "quiet";
}

function HealthItem({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className={`health-item ${ok ? "is-ok" : "is-off"}`}>
      <span className="health-dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

function WavePreview({ preview }: { preview: PreviewData }) {
  const samples = preview.samples?.[0] ?? [];
  const width = 620;
  const height = 136;
  const points = useMemo(() => {
    if (samples.length < 2) return "";
    const min = Math.min(...samples);
    const max = Math.max(...samples);
    const range = Math.max(max - min, 0.00001);
    return samples
      .map((value, index) => {
        const x = (index / (samples.length - 1)) * width;
        const y = height - 12 - ((value - min) / range) * (height - 24);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [samples]);

  return (
    <div className="preview-box">
      <div className="preview-head">
        <span>{preview.channel_names?.[0] ?? "信号预览"}</span>
        <span>{preview.sample_rate ? `${preview.sample_rate} Hz` : "—"}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="最近一段信号波形">
        <path className="grid-line" d={`M0 ${height / 2} H${width}`} />
        <polyline className="wave-line" points={points} />
      </svg>
      <p>{preview.notice}</p>
    </div>
  );
}

function GlovePreview({ preview }: { preview: PreviewData }) {
  return (
    <div className="preview-box glove-preview">
      <div><span>当前位置</span><strong>{preview.position ?? "—"}</strong></div>
      <div><span>目标位置</span><strong>{preview.target ?? "—"}</strong></div>
      <div><span>力矩状态</span><strong>{preview.released ? "已释放" : preview.armed ? "已启用" : "未知"}</strong></div>
      <div><span>拉力</span><strong>{preview.tension ?? "未配置传感器"}</strong></div>
      <p>{preview.notice}</p>
    </div>
  );
}

type DeviceCardProps = {
  kind: DeviceKind;
  drivers: DriverInfo[];
  entry: DeviceEntry;
  slot: DeviceSlot;
  preview?: PreviewData;
  busy: string | null;
  locked: boolean;
  onEntry: (entry: DeviceEntry) => void;
  onAction: (action: "discover" | "connect" | "preview" | "disconnect") => void;
};

function DeviceCard({
  kind,
  drivers,
  entry,
  slot,
  preview,
  busy,
  locked,
  onEntry,
  onAction,
}: DeviceCardProps) {
  const labels = LABELS[kind];
  const choices = drivers.filter((driver) => driver.kind === kind);
  const driver = choices.find((candidate) => candidate.id === entry.driver_id);
  const connected = ["data_valid", "connected", "degraded"].includes(slot.state);
  const isBusy = busy?.startsWith(`${kind}:`) ?? false;

  const updateField = (key: string, schema: FieldSchema, raw: string | boolean) => {
    let value: unknown = raw;
    if ((schema.type === "integer" || schema.type === "number") && typeof raw === "string") {
      value = raw === "" ? "" : schema.type === "integer" ? Number.parseInt(raw, 10) : Number(raw);
    }
    onEntry({ ...entry, config: { ...entry.config, [key]: value } });
  };

  return (
    <article className="device-card">
      <header className="device-header">
        <div className="device-index">{labels.index}</div>
        <div>
          <p className="eyebrow">{labels.eyebrow}</p>
          <h2>{labels.title}</h2>
        </div>
        <span className={`state-pill ${stateTone(slot.state)}`}>{stateLabel(slot.state)}</span>
      </header>

      <div className="field driver-field">
        <label htmlFor={`${kind}-driver`}>设备驱动</label>
        <select
          id={`${kind}-driver`}
          value={entry.driver_id}
          disabled={locked || connected || isBusy}
          onChange={(event) => {
            const selected = choices.find((candidate) => candidate.id === event.target.value);
            if (selected) onEntry({ driver_id: selected.id, config: defaults(selected) });
          }}
        >
          {choices.map((choice) => (
            <option key={choice.id} value={choice.id} disabled={!choice.available}>
              {choice.display_name}{choice.available ? "" : "（待接入）"}
            </option>
          ))}
        </select>
        {driver && (
          <p className={driver.available ? "field-help" : "field-help warning-text"}>
            {driver.available ? driver.description : driver.unavailable_reason}
          </p>
        )}
      </div>

      <div className="config-grid">
        {driver && Object.entries(driver.config_schema.properties).map(([key, schema]) => {
          const value = entry.config[key] ?? schema.default ?? "";
          return (
            <div className="field" key={key}>
              <label htmlFor={`${kind}-${key}`}>{schema.title ?? key}</label>
              {schema.type === "boolean" ? (
                <label className="toggle-row" htmlFor={`${kind}-${key}`}>
                  <input
                    id={`${kind}-${key}`}
                    type="checkbox"
                    checked={Boolean(value)}
                    disabled={locked || connected || isBusy || !driver.available}
                    onChange={(event) => updateField(key, schema, event.target.checked)}
                  />
                  <span>{Boolean(value) ? "开启" : "关闭"}</span>
                </label>
              ) : (
                <input
                  id={`${kind}-${key}`}
                  type={schema.type === "string" ? "text" : "number"}
                  value={String(value)}
                  min={schema.minimum}
                  max={schema.maximum}
                  step={schema.type === "integer" ? 1 : "any"}
                  disabled={locked || connected || isBusy || !driver.available}
                  onChange={(event) => updateField(key, schema, event.target.value)}
                />
              )}
            </div>
          );
        })}
      </div>

      {slot.discovered.length > 0 && (
        <div className="discovery-result">
          <span className="health-dot" />
          已发现：{slot.discovered.map((item) => item.name).join("、")}
        </div>
      )}

      <div className="health-panel">
        <div className="health-grid">
          <HealthItem ok={slot.health.transport_ok} label="传输连接" />
          <HealthItem ok={slot.health.stream_ok} label={kind === "glove" ? "状态读取" : "数据流"} />
          <HealthItem ok={slot.health.signal_ok} label={kind === "glove" ? "执行器响应" : "信号质量"} />
          <HealthItem ok={slot.health.time_sync_ok} label="时间对齐" />
        </div>
        <p>{slot.health.reason}</p>
      </div>

      <div className="button-row">
        <button
          className="button secondary"
          disabled={locked || connected || isBusy || !driver?.available}
          onClick={() => onAction("discover")}
        >
          发现设备
        </button>
        <button
          className="button primary"
          disabled={locked || connected || isBusy || !driver?.available}
          onClick={() => onAction("connect")}
        >
          {isBusy && busy === `${kind}:connect` ? "检查中…" : "连接并检查"}
        </button>
        <button
          className="button secondary"
          disabled={!connected || isBusy}
          onClick={() => onAction("preview")}
        >
          {kind === "glove" ? "读取状态" : "预览信号"}
        </button>
        <button
          className="button ghost"
          disabled={locked || !connected || isBusy}
          onClick={() => onAction("disconnect")}
        >
          断开
        </button>
      </div>

      {preview && (kind === "glove" ? <GlovePreview preview={preview} /> : <WavePreview preview={preview} />)}
      {kind === "glove" && (
        <div className="safety-note">
          <strong>连接检查不运动手套</strong>
          <span>这里只读设备状态。运动测试必须进入独立维护模式，并确认手套未佩戴。</span>
        </div>
      )}
    </article>
  );
}

export default function App() {
  const [drivers, setDrivers] = useState<DriverInfo[]>([]);
  const [profiles, setProfiles] = useState<ConnectionProfile[]>([]);
  const [entries, setEntries] = useState<DeviceEntries>(EMPTY_ENTRIES);
  const [system, setSystem] = useState<DeviceState>(EMPTY_STATE);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [profileName, setProfileName] = useState("新连接档案");
  const [previews, setPreviews] = useState<Partial<Record<DeviceKind, PreviewData>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("正在读取本机设备配置…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.drivers(), api.profiles(), api.state()])
      .then(([loadedDrivers, loadedProfiles, loadedState]) => {
        if (!active) return;
        setDrivers(loadedDrivers);
        setProfiles(loadedProfiles);
        setSystem(loadedState);
        if (loadedProfiles.length > 0) {
          const first = loadedProfiles[0];
          setEntries(first.devices);
          setProfileName(first.name);
          setActiveProfileId(first.id);
          setMessage(`已载入“${first.name}”，连接检查不会启动训练。`);
        } else {
          setEntries(initialEntries(loadedDrivers));
          setMessage("已载入默认配置，请逐项检查设备连接。");
        }
      })
      .catch((caught: Error) => {
        if (!active) return;
        setError(caught.message);
        setMessage("后端尚未启动，请先启动本地服务。");
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/v1/device-state`);
    socket.onmessage = (event) => setSystem(JSON.parse(event.data) as DeviceState);
    return () => socket.close();
  }, []);

  const readyCount = KINDS.filter((kind) => system.devices[kind].state === "data_valid").length;
  const allReady = readyCount === KINDS.length;

  const updateEntry = (kind: DeviceKind, entry: DeviceEntry) => {
    setEntries((current) => ({ ...current, [kind]: entry }));
    setPreviews((current) => ({ ...current, [kind]: undefined }));
  };

  const refreshState = async () => setSystem(await api.state());

  const runAction = async (
    kind: DeviceKind,
    action: "discover" | "connect" | "preview" | "disconnect",
  ) => {
    const entry = entries[kind];
    setBusy(`${kind}:${action}`);
    setError(null);
    try {
      if (action === "discover") {
        await api.discover(kind, entry.driver_id, entry.config);
        setMessage(`${LABELS[kind].title}发现完成，请核对候选设备。`);
      } else if (action === "connect") {
        await api.connect(kind, entry.driver_id, entry.config);
        setMessage(`${LABELS[kind].title}已完成连接与只读检查。`);
      } else if (action === "preview") {
        const preview = await api.preview(kind);
        setPreviews((current) => ({ ...current, [kind]: preview }));
        setMessage(`${LABELS[kind].title}预览已刷新。`);
      } else {
        await api.disconnect(kind);
        setMessage(`${LABELS[kind].title}已断开。`);
      }
      await refreshState();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setBusy(null);
    }
  };

  const connectAll = async () => {
    setBusy("all:connect");
    setError(null);
    try {
      for (const kind of KINDS) {
        const entry = entries[kind];
        await api.connect(kind, entry.driver_id, entry.config);
      }
      await refreshState();
      setMessage("三类设备均已完成连接检查，可以进入后续标定流程。当前页面不会启动训练。 ");
    } catch (caught) {
      await refreshState();
      setError(caught instanceof Error ? caught.message : "批量连接失败");
    } finally {
      setBusy(null);
    }
  };

  const saveProfile = async () => {
    setBusy("profile:save");
    setError(null);
    try {
      const saved = await api.saveProfile(activeProfileId, profileName, entries);
      setActiveProfileId(saved.id);
      setProfiles(await api.profiles());
      setMessage(`连接档案“${saved.name}”已保存。训练记录将保存档案快照，而不是只保存名称。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setBusy(null);
    }
  };

  const applyProfile = (profileId: string) => {
    const profile = profiles.find((candidate) => candidate.id === profileId);
    if (!profile) return;
    setActiveProfileId(profile.id);
    setProfileName(profile.name);
    setEntries(profile.devices);
    setPreviews({});
    setMessage(`已载入“${profile.name}”；连接状态不会被档案内容伪造，仍需重新检查。`);
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="RecoverHand 首页">
          <span className="brand-mark">RH</span>
          <span><strong>RecoverHand</strong><small>康复手上位机</small></span>
        </a>
        <nav aria-label="主导航">
          <span>患者与方案</span>
          <span>标定</span>
          <span>训练</span>
          <span>评估</span>
          <strong>设备连接</strong>
        </nav>
        <span className="local-badge">● 本机模式</span>
      </header>

      <section className="hero" id="top">
        <div>
          <p className="eyebrow">SYSTEM SETUP / 设备准备</p>
          <h1>把设备状态说清楚，<br />再开始一次训练。</h1>
          <p className="hero-copy">
            在同一处完成脑电、腕部肌电贴片与辅助手套的发现、配置、连接和只读检查。
            真实设备协议可以更换，训练流程不随接口变化。
          </p>
        </div>
        <div className={`readiness ${allReady ? "is-ready" : ""}`}>
          <span className="readiness-ring">{readyCount}<small>/ 3</small></span>
          <div>
            <p>{allReady ? "设备已就绪" : "等待设备检查"}</p>
            <span>{allReady ? "可以进入个体化标定" : "全部通过后才开放标定与训练"}</span>
          </div>
        </div>
      </section>

      <section className="profile-bar" aria-label="连接档案">
        <div className="profile-step"><span>1</span><div><strong>选择连接档案</strong><small>切换场景，不自动连接设备</small></div></div>
        <select value={activeProfileId ?? ""} onChange={(event) => applyProfile(event.target.value)} disabled={system.settings_locked}>
          {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          {profiles.length === 0 && <option value="">暂无已保存档案</option>}
        </select>
        <input
          aria-label="连接档案名称"
          value={profileName}
          disabled={system.settings_locked}
          onChange={(event) => setProfileName(event.target.value)}
        />
        <button className="button secondary" disabled={system.settings_locked || busy !== null} onClick={saveProfile}>
          保存当前档案
        </button>
        <button className="button primary connect-all" disabled={system.settings_locked || busy !== null || drivers.length === 0} onClick={connectAll}>
          {busy === "all:connect" ? "正在依次检查…" : "按当前档案检查全部"}
        </button>
      </section>

      {system.settings_locked && (
        <div className="locked-banner">当前处于标定或训练会话，连接参数已锁定。结束会话后才能修改。</div>
      )}
      <div className={`message-bar ${error ? "has-error" : ""}`} role="status" aria-live="polite">
        <span>{error ? "!" : "i"}</span>
        <p>{error ?? message}</p>
      </div>

      <section className="workflow-note">
        <p>推荐顺序</p>
        <div><span>加载档案</span><i>→</i><span>逐项连接</span><i>→</i><span>观察预览</span><i>→</i><strong>进入标定</strong></div>
        <small>“数据有效”只表示连接层通过，不等于意图识别有效，更不等于可以直接用于患者训练。</small>
      </section>

      <section className="device-list">
        {KINDS.map((kind) => (
          <DeviceCard
            key={kind}
            kind={kind}
            drivers={drivers}
            entry={entries[kind]}
            slot={system.devices[kind]}
            preview={previews[kind]}
            busy={busy}
            locked={system.settings_locked}
            onEntry={(entry) => updateEntry(kind, entry)}
            onAction={(action) => runAction(kind, action)}
          />
        ))}
      </section>

      <footer>
        <p><strong>原型边界</strong> · 当前仅实现设备连接与状态纵切面，不提供患者佩戴运动控制。</p>
        <span>所有数据留在本机 · v0.1</span>
      </footer>
    </main>
  );
}
