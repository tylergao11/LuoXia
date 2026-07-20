/** 把后端内部字段转成玩家可读中文，禁止直接 dump JSON。 */

const PHASE_LABEL = {
  PLAYER_TURN: "白日尚余",
  ADJUDICATING: "天道衡断",
  WORLD_EVOLVE: "夜色流转",
  DAY_ROLLOVER: "晨钟再起",
  MONTH_END: "月尽",
  GAME_OVER: "尘缘已尽",
  BOOT: "初入",
  ERROR: "天机紊乱",
};

const KIND_LABEL = {
  social: "人情",
  conflict: "争锋",
  death: "死讯",
  item: "器物",
  cultivation: "修为",
  law: "戒律",
  rumor: "流言",
  world: "世情",
  other: "杂录",
};

const SEVERITY_LABEL = {
  trivial: "微澜",
  minor: "寻常",
  major: "重大",
  critical: "惊变",
};

export function phaseLabel(p) {
  return PHASE_LABEL[p] || p || "—";
}

export function kindLabel(k) {
  return KIND_LABEL[k] || "事件";
}

export function severityLabel(s) {
  return SEVERITY_LABEL[s] || "";
}

export function formatCultivation(c) {
  if (!c || typeof c !== "object") return "深浅未测";
  const realm = c.realm || "深浅未测";
  const layer = c.layer != null ? `·第${c.layer}层` : "";
  const talent = c.talent === "high" ? "（根骨不凡）" : "";
  return `${realm}${layer}${talent}`;
}

export function formatInventory(list) {
  if (!list?.length) return "两袖清风";
  return list
    .map((i) => {
      const n = i.name || i.item_id || "异物";
      const q = i.qty != null && i.qty !== 1 ? `×${i.qty}` : "";
      return `${n}${q}`;
    })
    .join("、");
}

export function locationName(session, id) {
  if (!id) return "所在未明";
  const loc = session?.locations?.find((l) => l.id === id);
  return loc?.name || id;
}
