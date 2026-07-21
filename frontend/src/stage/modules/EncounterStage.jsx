/** 奇遇模块占位：可换插画/事件演出，权威仍走事件包 */
export function EncounterStage({ busy, stageMark, stageTitle, stageHint }) {
  return (
    <div className="stage-module stage-module-encounter">
      <div className="pull-sheet-stage-glow" />
      <div className="stage-encounter-badge">奇遇</div>
      <div className={`pull-sheet-stage-mark ${busy ? "pulse" : ""}`}>{stageMark || "奇"}</div>
      {stageTitle ? <div className="pull-sheet-stage-title">{stageTitle}</div> : null}
      {stageHint ? <div className="pull-sheet-stage-hint">{stageHint}</div> : null}
      {!busy ? <div className="pull-sheet-face-tip">点此切换画面</div> : null}
    </div>
  );
}
