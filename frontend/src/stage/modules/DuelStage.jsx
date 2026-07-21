function Mount({ place, mark, label, busy, qiLine }) {
  return (
    <div className={`stage-mount stage-mount-${place}`} data-mount={place}>
      <div className={`pull-sheet-stage-mark ${busy ? "pulse" : ""}`}>{mark || "·"}</div>
      {label ? <div className="stage-mount-label">{label}</div> : null}
      {qiLine ? <div className="stage-mount-qi">{qiLine}</div> : null}
    </div>
  );
}

/**
 * 交锋模块：己方左下、对方右上。
 * stagePayload 可带 qi 展示；点选在文字面 DuelPlayPanel。
 */
export function DuelStage({
  busy,
  stageMark,
  stageTitle,
  stageHint,
  stageSelf,
  stageFoe,
  stagePayload,
}) {
  const self = stageSelf || { mark: stageMark || "我", label: "己方" };
  const foe = stageFoe || { mark: "敌", label: "对方" };
  const qiMax = stagePayload?.qi_max;
  const qiSpent = stagePayload?.qi_spent;

  return (
    <div className="stage-module stage-module-duel">
      <div className="pull-sheet-stage-glow" />
      <Mount place="tr" mark={foe.mark} label={foe.label} busy={busy} />
      <div className="stage-duel-center">
        {stageTitle ? <div className="pull-sheet-stage-title">{stageTitle}</div> : null}
        {stageHint ? <div className="pull-sheet-stage-hint">{stageHint}</div> : null}
        {qiMax != null ? (
          <div className="stage-duel-qi-hint">
            气 {qiSpent ?? 0}/{qiMax}
          </div>
        ) : null}
        {!busy ? <div className="pull-sheet-face-tip">点此切换文字面点选</div> : null}
      </div>
      <Mount
        place="bl"
        mark={self.mark}
        label={self.label}
        busy={busy}
        qiLine={qiMax != null ? `气上限 ${qiMax}` : null}
      />
    </div>
  );
}
