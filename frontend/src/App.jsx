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
import { DuelPlayPanel } from "./stage/modules/DuelPlayPanel";

const SCENE_KEY = "_scene";

function countdownFromSession(session) {
  const row = (session?.clue_flags || []).find((f) => f.key === "xuanyin_countdown");
  return row?.value ?? null;
}

/** 服务端 chat 消息 → 前端气泡字段 */
function msgsToBubbles(messages) {
  return (messages || []).map((m) => {
    const eventId = m.eventId || m.event_id;
    if (m.role === "event_card") {
      return {
        ...m,
        eventId,
        sealed: m.sealed !== false && !m.read,
        headline: m.headline || m.card_headline || "旧事",
      };
    }
    if (m.role === "event_body" || m.role === "effect") {
      return { ...m, eventId };
    }
    return { ...m };
  });
}

function cloneChatStore(store) {
  const out = {};
  for (const [k, th] of Object.entries(store || {})) {
    out[k] = {
      actor_id: th?.actor_id || k,
      updated_day: th?.updated_day,
      messages: [...(th?.messages || [])],
    };
  }
  return out;
}

function sealedPreview(ev) {
  if (ev?.greyed) return "雾障未开。展卷后方可知一二。";
  return "因果已落卷中。点一下，正文在下。";
}

function EventCardList({ items, onSelect, session, readIds }) {
  /** 簿录页本地展卷（对话流的 reveal 找不到封条时，以前会「点了没反应」） */
  const [openId, setOpenId] = useState(null);

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
        const id = ev.event_id;
        const headline = ev.card_headline || ev.title || "旧事";
        const read = readIds?.has?.(id);
        const open = openId === id;
        const fullBody = String(ev.card_body || ev.summary || "").trim();
        // 未展卷：封条提示；已展卷未点开：摘要一行；点开：见下方正文
        const preview = open
          ? ""
          : read
            ? String(ev.summary || fullBody || "（无摘要）")
                .replace(/\s*\n+\s*/g, " ")
                .trim() || "（无摘要）"
            : sealedPreview(ev);
        const sev = severityLabel(ev.severity);
        return (
          <button
            type="button"
            key={id}
            className={`event-card ${ev.greyed ? "greyed" : ""} ${read || open ? "read" : "unread"} ${open ? "open" : ""} sev-${ev.severity || "minor"}`}
            onClick={() => {
              onSelect?.(ev);
              setOpenId((prev) => (prev === id ? null : id));
            }}
          >
            <div className="event-card-top">
              <span className="event-card-day">第{ev.day}日</span>
              <span className="event-card-kind">{kindLabel(ev.kind)}</span>
              {sev ? <span className="event-card-sev">{sev}</span> : null}
              <span className="event-card-track">
                {ev.track === "self" ? "己身" : "天下"}
              </span>
              {!read && !open && !ev.greyed ? (
                <span className="event-card-unread">未展卷</span>
              ) : null}
            </div>
            <div className="event-card-title">{headline}</div>
            {preview ? <div className="event-card-preview">{preview}</div> : null}
            {open && fullBody ? (
              <div className="event-card-body prose-box">{fullBody}</div>
            ) : null}
            {open && !fullBody ? (
              <div className="event-card-body event-card-body-empty">（卷中无字）</div>
            ) : null}
            <div className="event-card-foot">
              {!ev.greyed && ev.location ? (
                <span>{locationName(session, ev.location)}</span>
              ) : (
                <span>{ev.greyed ? "未明" : " "}</span>
              )}
              <span className="event-card-open">
                {ev.greyed ? "窥探" : open ? "收起" : read ? "再阅" : "点开展卷"}
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
  /** 按 actor_id 分仓；权威来自 session.chat_by_actor */
  const [chatByActor, setChatByActor] = useState({});
  const [locModal, setLocModal] = useState(null);
  const [actorModal, setActorModal] = useState(null);
  const [showStatus, setShowStatus] = useState(false);
  const [showClues, setShowClues] = useState(false);
  const [showBeliefs, setShowBeliefs] = useState(false);
  const [logTab, setLogTab] = useState("self");
  // 固定单行 log（错误/提示不占多行）
  const [logLine, setLogLine] = useState("");
  const [saves, setSaves] = useState([]);
  const [worlds, setWorlds] = useState([{ world_id: "luoxia", display_name: "落霞宗" }]);
  const [worldId, setWorldId] = useState("luoxia");
  const [healthInfo, setHealthInfo] = useState(null);
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

  const activeChatKey = talkMode && targetId ? targetId : SCENE_KEY;
  const bubbles = useMemo(
    () => msgsToBubbles(chatByActor[activeChatKey]?.messages || []),
    [chatByActor, activeChatKey]
  );

  function syncChatFromSession(sess) {
    if (!sess?.chat_by_actor) return;
    setChatByActor(cloneChatStore(sess.chat_by_actor));
  }

  function patchThread(actorId, updater) {
    const key = actorId || SCENE_KEY;
    setChatByActor((prev) => {
      const th = prev[key] || { actor_id: key, messages: [] };
      const messages = updater([...(th.messages || [])]);
      return {
        ...prev,
        [key]: { ...th, actor_id: key, messages },
      };
    });
  }

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
      syncChatFromSession(data.session);
      const guideEv = (data.session.recent_events || []).find((e) =>
        (e.tags || []).includes("guide")
      );
      const read = new Set();
      if (guideEv?.event_id) read.add(guideEv.event_id);
      // 须知只认服务端 dialogue._scene / guide 事件，前端不发明文案
      setTargetId(null);
      setTalkMode(false);
      setMainTab("chat");
      setReadEventIds(read);
      readEventIdsRef.current = read;
      sealedShownRef.current = new Set(read);
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
      syncChatFromSession(data.session);
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
        if (data.session.chat_by_actor) {
          syncChatFromSession(data.session);
        }
      }
      if (data.message) pushLog(data.message);
      if (body.type === "talk") {
        const shownSet = sealedShownRef.current;
        const news = data.new_events || [];

        // 事件权威 = 叙事卡；机械局势已由服务端写入 chat effect，前端不发明、不挂卡
        news.forEach((e) => {
          if (!e?.event_id) return;
          eventPayloadRef.current[e.event_id] = { event: e };
          shownSet.add(e.event_id);
        });
        if (data.session?.chat_by_actor) {
          syncChatFromSession(data.session);
        }
        // 无 chat_by_actor 则只认服务端会话；不发明 npc 气泡
      } else if (data.message && data.session?.phase !== "WORLD_EVOLVE") {
        patchThread(SCENE_KEY, (msgs) => [
          ...msgs,
          { role: "sys", text: data.message, id: `sys_${Date.now()}` },
        ]);
      }
      if (!data.ok) {
        pushLog(data.message || data.error_code || "未成");
      }

      // 入夜或耗尽余力触发夜色：自动续推至天明
      if (data?.ok && data.session?.phase === "WORLD_EVOLVE") {
        if (data.message) setEvolveHint(data.message);
        const finalS = await drainNight(data.session.session_id, data.session);
        if (finalS?.chat_by_actor) syncChatFromSession(finalS);
        return { ...data, session: finalS };
      }
      return data;
    } catch (e) {
      pushLog(String(e.message || e));
      if (body.type === "talk" && (body.target_id || targetId)) {
        const npcId = body.target_id || targetId;
        patchThread(npcId, (msgs) => msgs.filter((x) => !x.pending));
      }
    } finally {
      setLoading(false);
      setEvolveHint("");
    }
  }

  /**
   * 展卷：
   * - 对话流里有对应封条 → 在气泡下插入正文
   * - 因果簿点卡 → 列表自己展开正文（EventCardList openId）；此处只记已读 + 若对话里有封条则同步
   * - 已读再点不再 early-return（簿录要能「再阅」）
   */
  function revealEventInline(preferId, evHint) {
    const id = preferId || evHint?.event_id;
    if (!id) return;

    const cached = eventPayloadRef.current[id];
    const fromSession = session?.recent_events?.find((e) => e.event_id === id);
    const ev = { ...(cached?.event || fromSession || evHint || {}), event_id: id };
    eventPayloadRef.current[id] = { event: ev };

    const pureBody = String(ev.card_body || ev.summary || "").trim();
    const threadKey = talkMode && targetId ? targetId : activeChatKey;
    const alreadyRead = readEventIdsRef.current.has(id);

    if (!alreadyRead) {
      setReadEventIds((prev) => {
        const n = new Set(prev);
        n.add(id);
        readEventIdsRef.current = n;
        return n;
      });
      sealedShownRef.current.add(id);
    }

    patchThread(threadKey, (b) => {
      const idx = b.findIndex(
        (x) =>
          x.role === "event_card" && (x.eventId === id || x.event_id === id)
      );
      // 对话里没有这张封条（簿录点开常见）→ 不改线程
      if (idx < 0) return b;

      const opened = {
        role: "event_card",
        sealed: false,
        read: true,
        event_id: id,
        eventId: id,
        headline: ev.card_headline || ev.title || "旧事",
        day: ev.day,
        kind: ev.kind,
        severity: ev.severity,
      };
      const next = [...b];
      next[idx] = { ...next[idx], ...opened };
      if (
        b.some(
          (x) =>
            (x.eventId === id || x.event_id === id) && x.role === "event_body"
        )
      ) {
        return next;
      }
      if (pureBody) {
        next.splice(idx + 1, 0, {
          role: "event_body",
          event_id: id,
          eventId: id,
          text: pureBody,
        });
      }
      return next;
    });
  }

  async function sendTalk() {
    if (!targetId || !text.trim()) return;
    const utter = text.trim();
    const who = targetName || "对方";
    const npcId = targetId;
    setText("");
    // 乐观：只写入该人线程
    patchThread(npcId, (msgs) => [
      ...msgs,
      { role: "player", text: utter, id: `tmp_p_${Date.now()}` },
      {
        role: "npc",
        pending: true,
        text: `${who}正在思索…`,
        id: `tmp_pend_${Date.now()}`,
      },
    ]);
    try {
      await doAction({ type: "talk", target_id: npcId, utterance: utter });
    } catch {
      patchThread(npcId, (msgs) => [
        ...msgs.filter((x) => !x.pending),
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
    evolving && !locModal && !actorModal && !showStatus && !showClues && !showBeliefs;

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
                {countdownFromSession(session) != null && (
                  <>
                    {" · "}劫数
                    <strong>{countdownFromSession(session)}</strong>
                  </>
                )}
              </span>
            </div>
            <div className="topbar-actions">
              <button type="button" className="tb-btn" onClick={() => setShowStatus(true)}>
                情境
              </button>
              <button type="button" className="tb-btn" onClick={() => setShowBeliefs(true)}>
                见闻
              </button>
              <button type="button" className="tb-btn" onClick={() => setShowClues(true)}>
                隐情
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
        <div className="panel banner-panel ending-panel" style={{ borderColor: "var(--accent)" }}>
          <h3>因缘落定</h3>
          <p className="muted-p">
            {session.game_over_reason || phaseLabel(session.phase)}
            {" · "}第{session.day}日
          </p>
          {session.settlement_text && (
            <p className="ending-settlement">{session.settlement_text}</p>
          )}
          <h4 className="section-h">己身</h4>
          <div className="kv ending-kv">
            <div>
              <strong>身份</strong>
              {player?.identity?.title || player?.title || "—"}
            </div>
            <div>
              <strong>修为</strong>
              {formatCultivation(player?.cultivation)}
            </div>
            <div>
              <strong>所在</strong>
              {player?.location_label || "—"}
            </div>
            <div>
              <strong>灵石</strong>
              {player?.resources?.spirit_stones ?? 0}
            </div>
            <div>
              <strong>随身</strong>
              {formatInventory(player?.inventory)}
            </div>
            <div>
              <strong>存亡</strong>
              {player?.alive === false ? "已故" : "尚在"}
            </div>
          </div>
          {(player?.beliefs || []).length > 0 && (
            <>
              <h4 className="section-h">见闻</h4>
              <div className="logs compact belief-book">
                {(player.beliefs || []).map((b) => (
                  <div key={b.belief_id || b.proposition} className="log-item">
                    {b.category_label ? (
                      <span className="belief-cat-h">{b.category_label} · </span>
                    ) : null}
                    第{b.day ?? "?"}日 · {b.proposition}
                  </div>
                ))}
              </div>
            </>
          )}
          <h4 className="section-h">经历</h4>
          <div className="logs compact ending-chronicle">
            {(session.recent_events || []).length === 0 && (
              <div className="log-item greyed">无事件记录</div>
            )}
            {(session.recent_events || []).map((e) => (
              <div
                key={e.event_id || `${e.day}-${e.title}`}
                className={`log-item ${e.greyed ? "greyed" : ""}`}
              >
                <div className="log-item-title">
                  第{e.day ?? "?"}日 · {e.card_headline || e.title || "事"}
                </div>
                <div className="log-item-body">
                  {e.card_body || e.summary || ""}
                </div>
              </div>
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
              {/* 场景仓系统句（须知等）— 不与 NPC 对话混仓 */}
              {(chatByActor[SCENE_KEY]?.messages || []).length > 0 && (
                <div className="bubbles scene-bubbles" ref={!talkMode ? bubblesRef : undefined}>
                  {msgsToBubbles(chatByActor[SCENE_KEY].messages).map((b, i) => (
                    <div key={b.id || `scene-${i}`} className={`bubble ${b.role}`}>
                      {b.text}
                    </div>
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
                {!bubbles.length && (
                  <div className="bubble sys muted">尚未交谈。出言即可。</div>
                )}
                {bubbles.map((b, i) =>
                  b.role === "event_card" ? (
                    <button
                      key={b.eventId || b.id || `ev-${i}`}
                      type="button"
                      className={`bubble event-card-inline ${b.sealed ? "sealed" : "opened"}`}
                      disabled={!b.sealed}
                      onClick={() => {
                        if (!b.sealed) return;
                        const payload = eventPayloadRef.current[b.eventId];
                        const fromSession = session.recent_events?.find(
                          (e) => e.event_id === b.eventId
                        );
                        revealEventInline(
                          b.eventId,
                          payload?.event ||
                            fromSession || {
                              event_id: b.eventId,
                              card_headline: b.headline,
                              day: b.day,
                              kind: b.kind,
                            }
                        );
                      }}
                    >
                      <div className="event-card-title">{b.headline}</div>
                      <div className="event-card-preview">
                        {b.sealed ? "点一下，正文在下" : "已展卷"}
                      </div>
                    </button>
                  ) : (
                    <div
                      key={
                        b.id ||
                        (b.eventId
                          ? `${b.role}-${b.eventId}-${i}`
                          : `b-${i}`)
                      }
                      className={`bubble ${b.role}${b.pending ? " pending" : ""}`}
                    >
                      {b.role === "effect" ? (
                        <p className="effect-footnote">{b.text}</p>
                      ) : b.role === "event_body" ? (
                        <div className="prose-box">{b.text}</div>
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
            {session.locations.map((loc) => {
              const locked = !!loc.locked && !loc.is_current;
              return (
                <button
                  key={loc.id}
                  type="button"
                  className={`card-btn ${loc.is_current ? "current" : ""} ${
                    locked ? "locked-loc greyed-card" : ""
                  }`}
                  onClick={() => setLocModal(loc)}
                >
                  <div className="name">
                    {loc.name}
                    {locked ? <span className="loc-lock-tag">未开</span> : null}
                  </div>
                  <div className="sub">
                    {loc.is_current
                      ? "身在此处"
                      : locked
                        ? loc.lock_reason || "此处暂不可入"
                        : loc.summary}
                  </div>
                </button>
              );
            })}
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
            onSelect={(ev) => revealEventInline(ev.event_id, ev)}
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

      {/* 交锋：通用画模块 + 文字面点选 */}
      <PullSheet
        open={!!session?.encounter}
        onClose={() => {}}
        dismissible={false}
        busy={loading && !!session?.encounter}
        defaultFace="text"
        stageModule={session?.encounter?.stage_module || "duel"}
        stageMark={session?.encounter?.self_mark || "武"}
        stageTitle={
          session?.encounter
            ? `对峙 · ${session.encounter.foe_name || "对手"}`
            : "交锋"
        }
        stageHint="点选小招 · 双方确定后对拼"
        stageSelf={{
          mark: session?.encounter?.self_mark || "我",
          label: session?.encounter?.self_name || "己方",
        }}
        stageFoe={{
          mark: session?.encounter?.foe_mark || "敌",
          label: session?.encounter?.foe_name || "对方",
        }}
        stagePayload={session?.encounter || null}
      >
        {session?.encounter ? (
          <DuelPlayPanel
            encounter={session.encounter}
            loading={loading}
            onConfirm={async (moves) => {
              await doAction({
                type: "encounter",
                payload: { op: "confirm", moves },
              });
            }}
            onCancel={async () => {
              await doAction({
                type: "encounter",
                payload: { op: "cancel" },
              });
            }}
          />
        ) : null}
      </PullSheet>

      {/* 入夜：大弹窗；对话推演只用顶栏小提示 */}
      <PullSheet
        open={showNightSheet}
        onClose={() => {}}
        dismissible={false}
        busy={loading}
        defaultFace="anim"
        stageModule="tiandao"
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
        defaultFace="text"
        stageModule="location"
        stageMark={(locModal?.name || "地").slice(0, 1)}
        stageTitle={locModal?.name || ""}
        stageHint={
          locModal?.is_current
            ? "身在此处"
            : locModal?.locked
              ? "门禁未开"
              : "可行之路"
        }
        actions={[
          { key: "close", label: "罢了", onClick: () => setLocModal(null) },
          {
            key: "go",
            label: locModal?.is_current
              ? "身已在此"
              : locModal?.locked
                ? "不可入"
                : "前往",
            primary: true,
            disabled:
              loading ||
              locModal?.is_current ||
              locModal?.locked ||
              session.phase !== "PLAYER_TURN" ||
              ended,
            onClick: () => goToLocation(locModal.id),
          },
        ]}
      >
        <p className="sheet-copy">
          {locModal?.locked
            ? locModal?.lock_reason || "此处暂不可入"
            : locModal?.summary || "—"}
        </p>
      </PullSheet>

      {/* 人物：介绍 + 交谈/否 */}
      <PullSheet
        open={!!actorModal}
        onClose={() => setActorModal(null)}
        defaultFace="text"
        stageModule="actor"
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
                    key: "spar",
                    label: "切磋",
                    disabled:
                      loading ||
                      session.phase !== "PLAYER_TURN" ||
                      ended ||
                      !!session.encounter,
                    onClick: async () => {
                      const foeId = actorModal.id;
                      setActorModal(null);
                      await doAction({
                        type: "encounter",
                        target_id: foeId,
                        payload: { op: "start", foe_id: foeId },
                      });
                    },
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

      {/* 情境 */}
      <PullSheet
        open={showStatus}
        onClose={() => setShowStatus(false)}
        defaultFace="text"
        stageModule="status"
        stageMark="境"
        stageTitle="情境"
        stageHint={player.identity?.title || player.title || "客卿"}
        actions={[{ key: "ok", label: "合上", primary: true, onClick: () => setShowStatus(false) }]}
      >
        <div className="status-panel">
          <div className="kv">
            {(player?.situation_rows || []).map((row) => (
              <div key={row.key}>
                <strong>{row.label}</strong>
                {row.value}
              </div>
            ))}
            {!(player?.situation_rows || []).length ? (
              <p className="sheet-copy muted">尚无可见情境。</p>
            ) : null}
          </div>
        </div>
      </PullSheet>

      {/* 见闻（beliefs 投影） */}
      <PullSheet
        open={showBeliefs}
        onClose={() => setShowBeliefs(false)}
        defaultFace="text"
        stageModule="beliefs"
        stageMark="闻"
        stageTitle="见闻"
        stageHint="已写入心中的命题"
        actions={[
          { key: "ok", label: "合上", primary: true, onClick: () => setShowBeliefs(false) },
        ]}
      >
        <div className="status-panel belief-book">
          {(player?.beliefs || []).length === 0 ? (
            <p className="sheet-copy muted">尚无见闻。</p>
          ) : (
            <div className="logs compact">
              {(player.beliefs || []).map((b) => (
                <div key={b.belief_id || b.proposition} className="log-item">
                  {b.category_label ? (
                    <span className="belief-cat-h">{b.category_label} · </span>
                  ) : null}
                  第{b.day ?? "?"}日 · {b.proposition}
                </div>
              ))}
            </div>
          )}
        </div>
      </PullSheet>

      {/* 隐情 */}
      <PullSheet
        open={showClues}
        onClose={() => setShowClues(false)}
        defaultFace="text"
        stageModule="clues"
        stageMark="隐"
        stageTitle="隐情"
        stageHint="已握之机缘与未明之处"
        actions={[{ key: "ok", label: "合上", primary: true, onClick: () => setShowClues(false) }]}
      >
        <div className="status-panel">
          {(session.clue_flags || []).length === 0 ? (
            <p className="sheet-copy muted">尚无可见隐情。</p>
          ) : (
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
          )}
        </div>
      </PullSheet>
    </div>
  );
}
