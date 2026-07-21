import { useEffect, useState } from "react";

/**
 * 交锋文字面：点选小招（耗气）→ 确定对拼。
 * 胜负不在此算，只回传 move_ids。
 */
export function DuelPlayPanel({
  encounter,
  loading = false,
  onPick,
  onConfirm,
  onCancel,
}) {
  const moves = encounter?.moves || [];
  const qiMax = Number(encounter?.qi_max || 0);
  const maxHands = Number(encounter?.max_hands || 3);
  const serverPicked = encounter?.picked || [];
  const [picked, setPicked] = useState(serverPicked);

  const serverKey = `${encounter?.foe_id || ""}:${(encounter?.picked || []).join(",")}`;
  useEffect(() => {
    setPicked(Array.isArray(encounter?.picked) ? [...encounter.picked] : []);
  }, [serverKey]); // eslint-disable-line react-hooks/exhaustive-deps -- 仅在服务端序列变化时同步

  const byId = Object.fromEntries(moves.map((m) => [m.move_id, m]));
  const spent = picked.reduce((n, id) => n + Number(byId[id]?.qi_cost || 0), 0);
  const remain = qiMax - spent;

  function addMove(moveId) {
    const m = byId[moveId];
    if (!m || loading) return;
    if (picked.length >= maxHands) return;
    const cost = Number(m.qi_cost || 1);
    if (cost > remain) return;
    const next = [...picked, moveId];
    setPicked(next);
    onPick?.(next);
  }

  function removeAt(idx) {
    if (loading) return;
    const next = picked.filter((_, i) => i !== idx);
    setPicked(next);
    onPick?.(next);
  }

  return (
    <div className="duel-play" onClick={(e) => e.stopPropagation()}>
      <div className="duel-qi">
        气 {spent}/{qiMax}
        <span className="duel-qi-remain">剩余 {Math.max(0, remain)}</span>
      </div>
      {(encounter?.arts || []).length ? (
        <p className="sheet-copy muted">功法：{(encounter.arts || []).join("、")}</p>
      ) : null}
      <p className="sheet-copy muted">
        点选小招排好次序（至多{encounter?.max_hands || 3}手，耗气≤上限），再确定对拼。词条定棋盘，修为定砝码。
      </p>

      <div className="duel-seq">
        <div className="duel-seq-label">本场次序</div>
        {picked.length === 0 ? (
          <div className="duel-seq-empty">尚未点选</div>
        ) : (
          <div className="duel-seq-chips">
            {picked.map((id, idx) => (
              <button
                key={`${id}_${idx}`}
                type="button"
                className="duel-chip picked"
                disabled={loading}
                onClick={() => removeAt(idx)}
              >
                {idx + 1}. {byId[id]?.name || id}
                <span className="duel-chip-cost">-{byId[id]?.qi_cost || 1}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="duel-moves">
        <div className="duel-seq-label">可选小招</div>
        <div className="duel-move-grid">
          {moves.map((m) => {
            const cost = Number(m.qi_cost || 1);
            const disabled =
              loading || picked.length >= maxHands || cost > remain;
            return (
              <button
                key={m.move_id}
                type="button"
                className="duel-chip"
                disabled={disabled}
                onClick={() => addMove(m.move_id)}
              >
                <strong>{m.name}</strong>
                <span className="duel-chip-meta">
                  气{cost}
                  {(m.tags || []).length ? ` · ${(m.tags || []).join("/")}` : ""}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="duel-actions">
        <button
          type="button"
          className="sheet-btn sheet-btn-ghost"
          disabled={loading}
          onClick={() => onCancel?.()}
        >
          罢手
        </button>
        <button
          type="button"
          className="sheet-btn sheet-btn-primary"
          disabled={loading || picked.length === 0}
          onClick={() => onConfirm?.(picked)}
        >
          确定对拼
        </button>
      </div>
    </div>
  );
}
