import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import {
  formatCultivation,
  formatInventory,
  kindLabel,
  locationName,
  phaseLabel,
  severityLabel,
} from "./format";
import { PullSheet } from "./Sheet";

/** 把 effects 对象收成气泡文案（仅展卷后展示） */
function formatEffectsBubble(effects, otherName) {
  if (!effects || typeof effects !== "object") return "";
  if (effects.full_text) return effects.full_text;
  const blocks = [];
  if (effects.self_lines?.length) {
    blocks.push("【己身】\n" + effects.self_lines.map((x) => `· ${x}`).join("\n"));
  }
  const oname = effects.other_name || otherName || "对方";
  if (effects.other_lines?.length) {
    blocks.push(`【${oname}】\n` + effects.other_lines.map((x) => `· ${x}`).join("\n"));
  } else if (effects.other_id || otherName) {
    blocks.push(`【${oname}】\n· 未见明显状态流转`);
  }
  for (const o of effects.others || []) {
    if (o.lines?.length) {
      blocks.push(`【${o.name || o.id}】\n` + o.lines.map((x) => `· ${x}`).join("\n"));
    }
  }
  if (effects.world_lines?.length) {
    blocks.push("【天下】\n" + effects.world_lines.map((x) => `· ${x}`).join("\n"));
  }
  if (effects.ap_cost > 0) {
    blocks.push(`【余力】\n· 此番耗费 ${effects.ap_cost}`);
  }
  return blocks.join("\n\n");
}

/** 未展卷：列表/封条只露题面，不泄局势（客户端可已持有全文） */
function sealedPreview(ev) {
  if (ev?.greyed) return "雾障未开。展卷后方可知一二。";
  return "因果已落卷中。点开展卷，方见己身与对方之变。";
}

function EventCardList({ items, onSelect, session, readIds }) {
  if (!items?.length) {
    return (
      <div className="event-card-list">
        <div className="event-card greyed static" role="status">
          簿上尚空
        </div>
      </div>
    );
  }
  return (
    <div className="event-card-list">
      {items.map((ev) => {
        const headline = ev.card_headline || ev.title || "旧事";
        const read = readIds?.has?.(ev.event_id);
        // 正文完整给卡面；用 CSS 控制换行，不再硬截到一行
        const preview = read
          ? String(ev.summary || ev.card_body || "（无摘要）")
              .replace(/——局势——[\s\S]*/, "")
              .replace(/\s*\n+\s*/g, " ")
              .trim() || "（无摘要）"
          : sealedPreview(ev);
        const sev = severityLabel(ev.severity);
        return (
          <button
            type="button"
            key={ev.event_id}
            className={`event-card ${ev.greyed ? "greyed" : ""} ${read ? "read" : "unread"} sev-${ev.severity || "minor"}`}
            onClick={() => onSelect?.(ev)}
          >
            <div className="event-card-top">
              <span className="event-card-day">第{ev.day}日</span>
              <span className="event-card-kind">{kindLabel(ev.kind)}</span>
              {sev ? <span className="event-card-sev">{sev}</span> : null}
              <span className="event-card-track">
                {ev.track === "self" ? "己身" : "天下"}
              </span>
              {!read && !ev.greyed ? (
                <span className="event-card-unread">未展卷</span>
              ) : null}
            </div>
            <div className="event-card-title">{headline}</div>
            <div className="event-card-preview">{preview}</div>
            <div className="event-card-foot">
              {!ev.greyed && ev.location ? (
                <span>{locationName(session, ev.location)}</span>
              ) : (
                <span>{ev.greyed ? "未明" : " "}</span>
              )}
              <span className="event-card-open">
                {ev.greyed ? "窥探" : read ? "再阅" : "点开展卷"}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(false);
  const [bootError, setBootError] = useState("");
  const [targetId, setTargetId] = useState(null);
  const [text, setText] = useState("");
  const [bubbles, setBubbles] = useState([]);
  const [locModal, setLocModal] = useState(null);
  const [actorModal, setActorModal] = useState(null);
  const [showStatus, setShowStatus] = useState(false);
  const [logTab, setLogTab] = useState("self");
  // 固定单行 log（错误/提示不占多行）
  const [logLine, setLogLine] = useState("");
  const [saves, setSaves] = useState([]);
  const [worlds, setWorlds] = useState([{ world_id: "luoxia", display_name: "落霞宗" }]);
  const [worldId, setWorldId] = useState("luoxia");
  const [eventModal, setEventModal] = useState(null);
  const [eventSheetRevealed, setEventSheetRevealed] = useState(false);
  const [healthInfo, setHealthInfo] = useState(null);
  const [showHelp, setShowHelp] = useState(false);
  // 交谈模式：选中人并点「交谈」后才出现输入
  const [talkMode, setTalkMode] = useState(false);
  // chat=此地 | map | log
  const [mainTab, setMainTab] = useState("chat");
  const bubblesRef = useRef(null);
  const evolveBusyRef = useRef(false);
  const [evolveHint, setEvolveHint] = useState("");
  // 客户端可已持有事件全文；UI 仅在展卷后视为「已知」
  const [readEventIds, setReadEventIds] = useState(() => new Set());
  // event_id → { event, effects } 缓存（客户端已知）
  const eventPayloadRef = useRef({});
  // 已作为封条/展卷入对话流的事件 id（避免二次对话又挂上旧事件）
  const sealedShownRef = useRef(new Set());
  const readEventIdsRef = useRef(readEventIds);
  useEffect(() => {
    readEventIdsRef.current = readEventIds;
  }, [readEventIds]);

  const targetName = useMemo(() => {
    if (!session || !targetId) return null;
    return session.all_actors.find((a) => a.id === targetId)?.name;
  }, [session, targetId]);

  const ended =
    session &&
    (session.phase === "MONTH_END" ||
      session.phase === "GAME_OVER" ||
      session.game_over_reason);
  const evolving = session && session.phase === "WORLD_EVOLVE";

  // 新消息出现时滚到对话最底
  useEffect(() => {
    const el = bubblesRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [bubbles]);

  // 固定 log 行自动消
  useEffect(() => {
    if (!logLine) return;
    const t = setTimeout(() => setLogLine(""), 3200);
    return () => clearTimeout(t);
  }, [logLine]);

  function pushLog(msg) {
    if (!msg) return;
    setLogLine(String(msg).replace(/\s+/g, " ").trim());
  }

  useEffect(() => {
    api
      .listGames(8)
      .then((d) => setSaves(d.games || []))
      .catch(() => setSaves([]));
    api
      .worlds()
      .then((d) => {
        if (d.worlds?.length) setWorlds(d.worlds);
      })
      .catch(() => {});
    api
      .health()
      .then((d) => setHealthInfo(d))
      .catch(() => {});
  }, [session]);

  async function start() {
    setLoading(true);
    setBootError("");
    try {
      const data = await api.createGame(worldId);
      setSession(data.session);
      const guideEv = (data.session.recent_events || []).find((e) =>
        (e.tags || []).includes("guide")
      );
      const boot =
        guideEv?.summary ||
        (worldId === "qingxi"
          ? "你投宿青溪小驿，院中马嘶人声。"
          : "你以客卿弟子之身，踏入落霞宗外门客居。");
      setBubbles([{ role: "sys", text: boot }]);
      setTargetId(null);
      setTalkMode(false);
      setMainTab("chat");
      setShowHelp(true);
      setReadEventIds(new Set());
      readEventIdsRef.current = new Set();
      sealedShownRef.current = new Set();
      eventPayloadRef.current = {};
      localStorage.setItem("engine_session_id", data.session.session_id);
    } catch (e) {
      setBootError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function resume(id) {
    setLoading(true);
    setBootError("");
    try {
      const data = await api.getGame(id);
      setSession(data.session);
      setBubbles([{ role: "sys", text: `第${data.session.day}日，前缘未了，因果犹在。` }]);
      setTargetId(null);
      setTalkMode(false);
      setMainTab("chat");
      setReadEventIds(new Set());
      readEventIdsRef.current = new Set();
      sealedShownRef.current = new Set();
      eventPayloadRef.current = {};
      localStorage.setItem("engine_session_id", id);
      if (data.session?.phase === "WORLD_EVOLVE") {
        await drainNight(data.session.session_id, data.session);
      }
    } catch (e) {
      setBootError(String(e.message || e));
    } finally {
      setLoading(false);
      setEvolveHint("");
    }
  }

  /** 夜色步进：每请求一人/收日，直到离开 WORLD_EVOLVE */
  async function drainNight(sessionId, seedSession) {
    if (evolveBusyRef.current) return seedSession;
    evolveBusyRef.current = true;
    let cur = seedSession;
    try {
      // 安全上限：队列 + 收日 + 余量
      const maxSteps = Math.max(12, (cur?.evolve_queue?.length || 0) + 4);
      for (let i = 0; i < maxSteps; i++) {
        if (!cur || cur.phase !== "WORLD_EVOLVE") break;
        const data = await api.action(sessionId, { type: "end_day" });
        if (data.session) {
          cur = data.session;
          setSession(data.session);
          localStorage.setItem("engine_session_id", data.session.session_id);
        }
        if (data.message) {
          setEvolveHint(data.message);
          pushLog(data.message);
        }
        if (!data.ok) {
          pushLog(data.message || data.error_code || "夜事中断");
          break;
        }
        if (data.session?.phase !== "WORLD_EVOLVE") {
          if (data.message) pushLog(data.message);
          break;
        }
      }
      return cur;
    } finally {
      evolveBusyRef.current = false;
    }
  }

  async function doAction(body) {
    if (!session) return;
    setLoading(true);
    setEvolveHint("");
    try {
      const data = await api.action(session.session_id, body);
      if (data.session) {
        setSession(data.session);
        localStorage.setItem("engine_session_id", data.session.session_id);
      }
      if (data.message) pushLog(data.message);
      if (body.type === "talk") {
        // 对白立刻可见；事件/局势进「封条卡」——只挂「本轮」事件，绝不回退到旧事件
        const withoutPending = (list) => list.filter((x) => !x.pending);
        const readSet = readEventIdsRef.current;
        const shownSet = sealedShownRef.current;
        const effects = data.effects || {};

        // 1) 优先后端本轮 new_events（唯一可信来源）
        let pick = (data.new_events || []).find(
          (e) => e?.event_id && !e.greyed && !shownSet.has(e.event_id)
        );

        // 2) 兜底：recent 里「未展卷且未挂过封条」的最新一条（recent 为新→旧）
        if (!pick) {
          const recent = (data.session?.recent_events || []).filter(
            (e) =>
              e?.event_id &&
              e.involves_player &&
              !e.greyed &&
              !readSet.has(e.event_id) &&
              !shownSet.has(e.event_id)
          );
          pick = recent[0] || null;
        }

        // 3) 仅有局势无事件时，造本轮虚拟卡（唯一 id）
        let sealedId = pick?.event_id || null;
        if (sealedId) {
          eventPayloadRef.current[sealedId] = {
            event: pick,
            effects,
          };
          shownSet.add(sealedId);
        } else if (effects.full_text || effects.has_any) {
          sealedId = `fx_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
          eventPayloadRef.current[sealedId] = {
            event: {
              event_id: sealedId,
              day: data.session?.day,
              title: "言谈余波",
              card_headline: "言谈余波",
              kind: "social",
              severity: "trivial",
              track: "self",
              involves_player: true,
              summary: data.message || "一席话落定",
              card_body: data.message || "",
            },
            effects,
          };
          shownSet.add(sealedId);
        }

        setBubbles((b) => {
          const next = [
            ...withoutPending(b),
            ...(data.npc_utterance
              ? [{ role: "npc", text: data.npc_utterance }]
              : [{ role: "sys", text: "对方未答话。" }]),
          ];
          if (sealedId && eventPayloadRef.current[sealedId]) {
            const { event: ev } = eventPayloadRef.current[sealedId];
            next.push({
              role: "event_card",
              sealed: true,
              eventId: sealedId,
              headline: ev.card_headline || ev.title || "旧事",
              day: ev.day,
              kind: ev.kind,
              severity: ev.severity,
            });
          } else if (data.message) {
            next.push({ role: "sys", text: data.message });
          }
          return next;
        });
      } else if (data.message && data.session?.phase !== "WORLD_EVOLVE") {
        setBubbles((b) => [...b, { role: "sys", text: data.message }]);
      }
      if (!data.ok) {
        pushLog(data.message || data.error_code || "未成");
      }

      // 入夜或耗尽余力触发夜色：自动续推至天明
      if (data?.ok && data.session?.phase === "WORLD_EVOLVE") {
        if (data.message) setEvolveHint(data.message);
        const finalS = await drainNight(data.session.session_id, data.session);
        return { ...data, session: finalS };
      }
      return data;
    } catch (e) {
      pushLog(String(e.message || e));
      if (body.type === "talk") {
        setBubbles((b) => b.filter((x) => !x.pending));
      }
    } finally {
      setLoading(false);
      setEvolveHint("");
    }
  }

  /** 点事件卡 → 明确弹窗（动画位 + 启）；按 event_id 取缓存，禁止串卡 */
  function openEventSheet(ev, preferId) {
    if (!ev && !preferId) return;
    const id = preferId || ev.event_id;
    if (!id) return;
    const cached = eventPayloadRef.current[id];
    // 缓存优先（本轮封条挂的是完整 payload）；再与传入/会话列表合并
    const base = cached?.event || ev || {};
    const merged = { ...base, ...(ev || {}), event_id: id };
    let effects = { ...(cached?.effects || {}) };
    if (!effects.full_text && merged.card_body && String(merged.card_body).includes("——局势——")) {
      const part = String(merged.card_body).split("——局势——")[1] || "";
      effects = { ...effects, full_text: part.trim() };
    }
    eventPayloadRef.current[id] = { event: merged, effects };
    const already = readEventIdsRef.current.has(id);
    setEventSheetRevealed(already);
    setEventModal({ ...merged, _effects: effects });
  }

  /**
   * 点「启」：弹窗揭示 + 写入对话流（UI 至此才「已知」）
   */
  function qiEventSheet() {
    const ev = eventModal;
    if (!ev || ev.greyed) return;
    const id = ev.event_id;
    const cached = eventPayloadRef.current[id] || { event: ev, effects: ev._effects || {} };
    const effects = cached.effects || ev._effects || {};
    eventPayloadRef.current[id] = { event: { ...cached.event, ...ev }, effects };

    const already = readEventIds.has(id);
    setEventSheetRevealed(true);
    setReadEventIds((prev) => {
      const n = new Set(prev);
      n.add(id);
      readEventIdsRef.current = n;
      return n;
    });
    sealedShownRef.current.add(id);

    const otherName =
      effects.other_name ||
      (ev.actor_ids || [])
        .map((aid) => session?.all_actors?.find((a) => a.id === aid)?.name)
        .filter(Boolean)
        .find((n) => n) ||
      "";
    const effectText =
      formatEffectsBubble(effects, otherName) ||
      "【局势】\n· 暂无可见的状态变化";
    const pureBody = String(ev.card_body || ev.summary || "")
      .split("——局势——")[0]
      .trim();

    setMainTab("chat");
    setBubbles((b) => {
      const mapped = b.map((x) =>
        x.role === "event_card" && x.eventId === id
          ? { ...x, sealed: false, read: true }
          : x
      );
      if (already) return mapped;
      return [
        ...mapped,
        {
          role: "sys",
          text: `你启卷「${ev.card_headline || ev.title || "旧事"}」。`,
        },
        ...(pureBody ? [{ role: "sys", text: pureBody }] : []),
        {
          role: "effect",
          eventId: id,
          text: effectText,
        },
      ];
    });
  }

  function closeEventSheet() {
    setEventModal(null);
    setEventSheetRevealed(false);
  }

  async function sendTalk() {
    if (!targetId || !text.trim()) return;
    const utter = text.trim();
    const who = targetName || "对方";
    setText("");
    // 己方气泡 + 占位「正在思考」，避免长等待像卡住
    setBubbles((b) => [
      ...b,
      { role: "player", text: utter },
      {
        role: "npc",
        pending: true,
        text: `${who}正在思索…`,
      },
    ]);
    try {
      await doAction({ type: "talk", target_id: targetId, utterance: utter });
    } catch {
      setBubbles((b) => [
        ...b.filter((x) => !x.pending),
        { role: "sys", text: "言路中断，未得回音。" },
      ]);
    }
  }

  async function goToLocation(locId) {
    setLocModal(null);
    const data = await doAction({ type: "move", location_id: locId });
    if (data?.ok) {
      setTargetId(null);
      setTalkMode(false);
      setMainTab("chat");
      pushLog("身已至此。可点眼前之人。");
    }
  }

  if (!session) {
    const lastId =
      typeof localStorage !== "undefined"
        ? localStorage.getItem("engine_session_id") ||
          localStorage.getItem("luoxia_session_id")
        : null;
    return (
      <div className="boot">
        <div className="boot-inner">
          <h1 className="boot-title">
            {worlds.find((w) => w.world_id === worldId)?.display_name || "世界引擎"}
          </h1>
          <p className="boot-lead">一言一念，皆入因果。天道衡断，众生自转。</p>
          {healthInfo && (
            <div className="boot-health">
              <span className="boot-chip">
                {String(healthInfo.llm_mode || "").startsWith("llm")
                  ? "天机通明"
                  : "虚演天机"}
              </span>
              <span className="boot-chip">
                {healthInfo.llm_mode || healthInfo.llm_model || "—"}
              </span>
            </div>
          )}
          {bootError && <div className="error">{bootError}</div>}
          <label className="boot-field">
            <span>择境</span>
            <select value={worldId} onChange={(e) => setWorldId(e.target.value)}>
              {worlds.map((w) => (
                <option key={w.world_id} value={w.world_id}>
                  {w.display_name}
                </option>
              ))}
            </select>
          </label>
          <button className="primary boot-cta" type="button" disabled={loading} onClick={start}>
            {loading ? "启缘中…" : "踏入山门"}
          </button>
          {lastId && (
            <button
              className="ghost boot-cta"
              type="button"
              disabled={loading}
              onClick={() => resume(lastId)}
            >
              续上前缘
            </button>
          )}
          {saves.length > 0 && (
            <div className="save-list">
              <div className="stat">旧日残卷</div>
              {saves.slice(0, 4).map((g) => (
                <button
                  key={g.session_id}
                  type="button"
                  className="card-btn"
                  onClick={() => resume(g.session_id)}
                >
                  <div className="name">
                    {(worlds.find((w) => w.world_id === g.world_id)?.display_name ||
                      g.world_id)}{" "}
                    · 第{g.day}日
                  </div>
                  <div className="sub">{phaseLabel(g.phase)}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  const player = session.player;
  const canTalk = session.phase === "PLAYER_TURN" && targetId && player.alive && !ended;
  // 自己排到最后，先展示可互动 NPC
  const actorsHere = [...(session.actors_here || [])].sort(
    (a, b) => Number(!!a.is_player) - Number(!!b.is_player)
  );
  const logs =
    logTab === "self"
      ? session.logs_self || []
      : logTab === "world"
        ? session.logs_world || []
        : session.recent_events || [];
  const locName = locationName(session, player.location);
  // 对话/行动推演：仅顶栏小提示；入夜：大弹窗
  const topBusy = loading && !evolving;
  const showNightSheet =
    evolving && !eventModal && !locModal && !actorModal && !showHelp && !showStatus;
  const eventEffects = eventModal
    ? eventPayloadRef.current[eventModal.event_id]?.effects || eventModal._effects || {}
    : {};
  const pureEventBody = eventModal
    ? String(eventModal.card_body || eventModal.summary || "")
        .split("——局势——")[0]
        .trim()
    : "";
  const eventEffectText = eventModal
    ? formatEffectsBubble(eventEffects, eventEffects.other_name) ||
      (eventModal.greyed ? "雾障未开，难窥端倪。" : "")
    : "";

  return (
    <div className="app">
      <header className={`topbar ${topBusy ? "is-busy" : ""}`}>
        {topBusy ? (
          <div className="topbar-busy-line" role="status" aria-live="polite">
            <span className="topbar-busy-dot" aria-hidden />
            <span className="topbar-busy-text">天道衡断中</span>
          </div>
        ) : (
          <div className="topbar-main">
            <div className="topbar-left">
              <span className="brand">
                {worlds.find((w) => w.world_id === session.world_id)?.display_name ||
                  session.world_id}
              </span>
              <span className="stat topbar-stat">
                第<strong>{session.day}</strong>/{session.max_days}日
                {" · "}余力<strong>{session.ap}</strong>
                {session.world_flags_public?.xuanyin_countdown != null && (
                  <>
                    {" · "}劫数
                    <strong>
                      {typeof session.world_flags_public.xuanyin_countdown === "object"
                        ? session.world_flags_public.xuanyin_countdown.value
                        : session.world_flags_public.xuanyin_countdown}
                    </strong>
                  </>
                )}
              </span>
            </div>
            <div className="topbar-actions">
              <button type="button" className="tb-btn" onClick={() => setShowHelp(true)}>
                须知
              </button>
              <button type="button" className="tb-btn" onClick={() => setShowStatus(true)}>
                己身
              </button>
              <button
                type="button"
                className="tb-btn"
                disabled={session.phase !== "PLAYER_TURN" || ended || loading}
                onClick={() => doAction({ type: "end_day" })}
              >
                入夜
              </button>
            </div>
          </div>
        )}
      </header>

      {/* 固定单行 log：错误/提示只占这一行 */}
      <div className={`log-bar ${logLine ? "has-msg" : ""}`} role="status" aria-live="polite">
        <span className="log-bar-text">{logLine || " "}</span>
      </div>

      {ended && (
        <div className="panel banner-panel" style={{ borderColor: "var(--accent)" }}>
          <h3>因缘落定</h3>
          <p className="muted-p">{session.game_over_reason || phaseLabel(session.phase)}</p>
          <div className="tag-row">
            {(session.ending_tags || []).map((t) => (
              <span key={t} className="tag-pill">
                {t}
              </span>
            ))}
          </div>
          <button className="primary btn-block" type="button" onClick={start} style={{ marginTop: 12 }}>
            再入红尘
          </button>
        </div>
      )}

      <div className="layout">
        {/* 此地：展示角色，非默认对话框 */}
        <div className={`panel dialogue-panel tab-panel ${mainTab === "chat" ? "active" : ""}`}>
          {/* 选人：谈话时整页让给聊天 */}
          {!talkMode && (
            <>
              <div className="scene-head">
                <div className="scene-head-title">{locName}</div>
                <div className="scene-head-sub">眼前之人 · 点选观其详</div>
              </div>
              <div className="actor-grid">
                {actorsHere.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    className={`actor-tile ${!a.alive ? "greyed-card" : ""} ${
                      a.is_player ? "is-self" : ""
                    }`}
                    onClick={() => {
                      if (a.is_player) {
                        setShowStatus(true);
                        return;
                      }
                      setActorModal(a);
                    }}
                  >
                    <div className="actor-tile-mark">{(a.name || "?").slice(0, 1)}</div>
                    <div className="actor-tile-name">
                      {a.name}
                      {a.is_player ? "（己）" : ""}
                    </div>
                    <div className="actor-tile-sub">{a.alive ? a.title || "—" : "已故"}</div>
                  </button>
                ))}
                {!actorsHere.length && <div className="stat empty-scene">四下无人</div>}
              </div>
              {bubbles.some((b) => b.role === "event_card" && b.sealed) && (
                <div className="pending-events">
                  {bubbles
                    .filter((b) => b.role === "event_card" && b.sealed)
                    .map((b) => (
                      <button
                        key={b.eventId}
                        type="button"
                        className="event-card-inline sealed mini"
                        onClick={() => {
                          const payload = eventPayloadRef.current[b.eventId];
                          const fromSession = session.recent_events?.find(
                            (e) => e.event_id === b.eventId
                          );
                          openEventSheet(payload?.event || fromSession || { event_id: b.eventId, card_headline: b.headline }, b.eventId);
                        }}
                      >
                        <span className="event-card-title">{b.headline}</span>
                        <span className="event-card-open">展卷</span>
                      </button>
                    ))}
                </div>
              )}
            </>
          )}

          {/* 谈话页：占满选人区 */}
          {talkMode && targetId && (
            <div className="talk-pane talk-pane-full">
              <div className="talk-pane-head">
                <div className="talk-pane-who">
                  <span className="talk-pane-dot" />
                  <span className="talk-pane-name">与{targetName}言</span>
                  <span className="talk-pane-loc">{locName}</span>
                </div>
                <button
                  type="button"
                  className="btn-baton"
                  onClick={() => {
                    setTalkMode(false);
                    setTargetId(null);
                    pushLog("言尽而退。");
                  }}
                >
                  <span className="btn-baton-icon">↩</span>
                  罢谈
                </button>
              </div>
              <div className="bubbles" ref={bubblesRef}>
                {bubbles.map((b, i) =>
                  b.role === "event_card" ? (
                    <button
                      key={b.eventId || `ev-${i}`}
                      type="button"
                      className={`bubble event-card-inline ${b.sealed ? "sealed" : "opened"}`}
                      onClick={() => {
                        const payload = eventPayloadRef.current[b.eventId];
                        const fromSession = session.recent_events?.find(
                          (e) => e.event_id === b.eventId
                        );
                        openEventSheet(
                          payload?.event || fromSession || {
                            event_id: b.eventId,
                            card_headline: b.headline,
                            day: b.day,
                            kind: b.kind,
                          },
                          b.eventId
                        );
                      }}
                    >
                      <div className="event-card-title">{b.headline}</div>
                      <div className="event-card-preview">
                        {b.sealed ? "点开展卷" : "已展卷"}
                      </div>
                    </button>
                  ) : (
                    <div
                      key={b.eventId || `b-${i}`}
                      className={`bubble ${b.role}${b.pending ? " pending" : ""}`}
                    >
                      {b.role === "effect" ? (
                        <>
                          <div className="effect-title">局势变化</div>
                          <pre className="effect-body">{b.text}</pre>
                        </>
                      ) : (
                        b.text
                      )}
                    </div>
                  )
                )}
              </div>
            </div>
          )}
        </div>

        <div className={`panel tab-panel ${mainTab === "map" ? "active" : ""}`}>
          <h3>行途</h3>
          <div className="list">
            {session.locations.map((loc) => (
              <button
                key={loc.id}
                type="button"
                className={`card-btn ${loc.is_current ? "current" : ""}`}
                onClick={() => setLocModal(loc)}
              >
                <div className="name">{loc.name}</div>
                <div className="sub">{loc.is_current ? "身在此处" : loc.summary}</div>
              </button>
            ))}
          </div>
        </div>

        <div className={`panel tab-panel log-panel ${mainTab === "log" ? "active" : ""}`}>
          <h3>因果簿</h3>
          <div className="log-tabs">
            <button
              type="button"
              className={logTab === "self" ? "active" : ""}
              onClick={() => setLogTab("self")}
            >
              己身
            </button>
            <button
              type="button"
              className={logTab === "world" ? "active" : ""}
              onClick={() => setLogTab("world")}
            >
              天下
            </button>
            <button
              type="button"
              className={logTab === "all" ? "active" : ""}
              onClick={() => setLogTab("all")}
            >
              尽览
            </button>
          </div>
          <EventCardList
            items={logs}
            session={session}
            readIds={readEventIds}
            onSelect={(ev) => openEventSheet(ev)}
          />
        </div>
      </div>

      <div className="bottom-dock">
        {mainTab === "chat" && talkMode && targetId && (
          <div className="composer">
            <input
              value={text}
              disabled={!canTalk || loading}
              placeholder={`与${targetName}言…`}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendTalk()}
            />
            <button
              className="primary"
              type="button"
              disabled={!canTalk || loading}
              onClick={sendTalk}
            >
              言出
            </button>
          </div>
        )}
        <nav className="nav-tabs nav-tabs-3" aria-label="主导航">
          <button
            type="button"
            className={mainTab === "chat" ? "active" : ""}
            onClick={() => setMainTab("chat")}
          >
            此地
          </button>
          <button
            type="button"
            className={mainTab === "map" ? "active" : ""}
            onClick={() => setMainTab("map")}
          >
            行途
          </button>
          <button
            type="button"
            className={mainTab === "log" ? "active" : ""}
            onClick={() => setMainTab("log")}
          >
            簿录
          </button>
        </nav>
      </div>

      {/* 入夜：大弹窗；对话推演只用顶栏小提示 */}
      <PullSheet
        open={showNightSheet}
        onClose={() => {}}
        dismissible={false}
        busy={loading}
        defaultFace="anim"
        animSlot="tiandao"
        stageMark="夜"
        stageTitle="夜色流转"
        stageHint={
          evolveHint ||
          `${session.evolve_index || 0}/${(session.evolve_queue || []).length || "?"} · ${
            session.evolve_last_actor_name || "众生自转"
          }`
        }
        actions={
          evolving && !loading
            ? [
                {
                  key: "resume",
                  label: "续观夜事",
                  primary: true,
                  onClick: () => doAction({ type: "end_day" }),
                },
              ]
            : []
        }
      >
        <p className="sheet-copy muted">众生夜行，一点一滴皆入簿。可稍候或点续观。</p>
      </PullSheet>

      {/* 地点 */}
      <PullSheet
        open={!!locModal}
        onClose={() => setLocModal(null)}
        defaultFace="anim"
        animSlot="location"
        stageMark={(locModal?.name || "地").slice(0, 1)}
        stageTitle={locModal?.name || ""}
        stageHint={locModal?.is_current ? "身在此处" : "可行之路"}
        actions={[
          { key: "close", label: "罢了", onClick: () => setLocModal(null) },
          {
            key: "go",
            label: locModal?.is_current ? "身已在此" : "前往",
            primary: true,
            disabled:
              loading ||
              locModal?.is_current ||
              session.phase !== "PLAYER_TURN" ||
              ended,
            onClick: () => goToLocation(locModal.id),
          },
        ]}
      >
        <p className="sheet-copy">{locModal?.summary || "—"}</p>
      </PullSheet>

      {/* 人物：介绍 + 交谈/否 */}
      <PullSheet
        open={!!actorModal}
        onClose={() => setActorModal(null)}
        defaultFace="anim"
        animSlot="actor"
        stageMark={(actorModal?.name || "人").slice(0, 1)}
        stageTitle={actorModal?.name || ""}
        stageHint={actorModal?.title || (actorModal?.alive ? "在场" : "已故")}
        actions={
          actorModal?.is_player
            ? [{ key: "close", label: "合上", primary: true, onClick: () => setActorModal(null) }]
            : !actorModal?.alive
              ? [{ key: "close", label: "合上", primary: true, onClick: () => setActorModal(null) }]
              : [
                  {
                    key: "no",
                    label: "否",
                    onClick: () => setActorModal(null),
                  },
                  {
                    key: "talk",
                    label: "交谈",
                    primary: true,
                    disabled: loading || session.phase !== "PLAYER_TURN" || ended,
                    onClick: () => {
                      setTargetId(actorModal.id);
                      setTalkMode(true);
                      setMainTab("chat");
                      setActorModal(null);
                      pushLog(`与${actorModal.name}交谈。`);
                    },
                  },
                ]
        }
      >
        {actorModal && (
          <div className="sheet-actor-info">
            <p className="sheet-copy">{actorModal.summary || actorModal.title || "—"}</p>
            {actorModal.cultivation && !actorModal.cultivation_greyed ? (
              <div className="event-detail-row">
                <strong>修为</strong>
                {formatCultivation(actorModal.cultivation)}
              </div>
            ) : null}
            <div className="event-detail-row">
              <strong>所在</strong>
              {locName}
            </div>
          </div>
        )}
      </PullSheet>

      {/* 事件卡：启 */}
      <PullSheet
        open={!!eventModal}
        onClose={closeEventSheet}
        defaultFace="anim"
        animSlot="event-reveal"
        stageMark={eventSheetRevealed ? "开" : "封"}
        stageTitle={eventModal?.card_headline || eventModal?.title || "旧事"}
        stageHint={
          eventModal?.greyed
            ? "雾障未开"
            : eventSheetRevealed
              ? "因果已启"
              : "点「启」展卷"
        }
        actions={[
          { key: "close", label: "合卷", onClick: closeEventSheet },
          {
            key: "qi",
            label: eventModal?.greyed
              ? "未明"
              : eventSheetRevealed && readEventIds.has(eventModal?.event_id)
                ? "已启"
                : "启",
            primary: true,
            disabled:
              !eventModal ||
              eventModal.greyed ||
              (eventSheetRevealed && readEventIds.has(eventModal.event_id)),
            onClick: qiEventSheet,
          },
        ]}
      >
        {eventModal && (
          <>
            <div className="event-detail-meta">
              {eventModal.day != null ? <span>第{eventModal.day}日</span> : null}
              <span>{eventModal.track === "self" ? "己身" : "天下"}</span>
              <span>{kindLabel(eventModal.kind)}</span>
            </div>
            {!eventSheetRevealed && !eventModal.greyed ? (
              <p className="sheet-copy muted">
                卷中有字。未启之前，局势不入眼；须点「启」，方成已知。
              </p>
            ) : null}
            {(eventSheetRevealed || eventModal.greyed) && (
              <div className="event-sheet-revealed">
                {eventModal.greyed ? (
                  <p className="grey-text">雾障未开，难窥端倪。</p>
                ) : (
                  <>
                    {pureEventBody ? (
                      <div className="prose-box">{pureEventBody}</div>
                    ) : null}
                    {eventEffectText ? (
                      <div className="bubble effect event-sheet-effect">
                        <div className="effect-title">局势变化</div>
                        <pre className="effect-body">{eventEffectText}</pre>
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            )}
          </>
        )}
      </PullSheet>

      {/* 须知 */}
      <PullSheet
        open={showHelp}
        onClose={() => setShowHelp(false)}
        defaultFace="anim"
        animSlot="help"
        stageMark="知"
        stageTitle="客卿须知"
        stageHint="入门便览"
        actions={[{ key: "ok", label: "知道了", primary: true, onClick: () => setShowHelp(false) }]}
      >
        <div className="status-panel">
          <p>
            <strong>此地</strong>
            ：见眼前之人，点选观详，可交谈。
          </p>
          <p>
            <strong>行途</strong>
            ：择地前往，居中弹窗观详。
          </p>
          <p>
            <strong>簿录</strong>
            ：事件封条，点开展卷，再点「启」。
          </p>
          <p>
            <strong>入夜</strong>
            ：余力尽或自请入夜，众生自转。
          </p>
          <p>
            <strong>弹窗</strong>
            ：先见「画」，点画面可切换文字；点空白处合上。
          </p>
        </div>
      </PullSheet>

      {/* 己身 */}
      <PullSheet
        open={showStatus}
        onClose={() => setShowStatus(false)}
        defaultFace="anim"
        animSlot="status"
        stageMark="己"
        stageTitle="己身境况"
        stageHint={player.identity?.title || player.title || "客卿"}
        actions={[{ key: "ok", label: "合上", primary: true, onClick: () => setShowStatus(false) }]}
      >
        <div className="status-panel">
          <div className="kv">
            <div>
              <strong>身份</strong>
              {player.identity?.title || player.title || "—"}
            </div>
            <div>
              <strong>修为</strong>
              {formatCultivation(player.cultivation)}
            </div>
            <div>
              <strong>灵石</strong>
              {player.resources?.spirit_stones ?? 0}
            </div>
            <div>
              <strong>所在</strong>
              {player.location_label || locName}
            </div>
            <div>
              <strong>随身</strong>
              {formatInventory(player.inventory)}
            </div>
          </div>
          {(session.case_lines || []).length > 0 && (
            <>
              <h3 className="section-h">案线</h3>
              <div className="case-lines">
                {(session.case_lines || []).map((line) => (
                  <div key={line.id} className="case-line">
                    <div className="case-line-title">{line.title}</div>
                    <div className="case-stages">
                      {(line.stages || []).map((st) => (
                        <button
                          key={st.id}
                          type="button"
                          className={`case-stage ${st.revealed ? "on" : "off"}`}
                          title={st.revealed ? st.blurb || st.label_true : "尚未坐实"}
                          onClick={() => {
                            if (st.revealed && st.blurb) pushLog(st.blurb);
                          }}
                        >
                          {st.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
          {(session.clue_flags || []).length > 0 && (
            <>
              <h3 className="section-h">隐情</h3>
              <div className="clue-flags">
                {(session.clue_flags || []).map((f) => (
                  <div
                    key={f.key}
                    className={`clue-flag-row ${f.greyed ? "greyed" : ""}`}
                  >
                    <span className="clue-flag-label">{f.label_zh}</span>
                    <span className="clue-flag-val">{f.display}</span>
                  </div>
                ))}
              </div>
            </>
          )}
          <h3 className="section-h">见闻</h3>
          <div className="logs compact">
            {(player.beliefs || []).length === 0 && (
              <div className="log-item greyed">心中尚无沉淀</div>
            )}
            {(player.beliefs || []).slice(0, 8).map((b) => (
              <div key={b.belief_id} className="log-item">
                第{b.day}日 · {b.proposition}
              </div>
            ))}
          </div>
        </div>
      </PullSheet>
    </div>
  );
}
