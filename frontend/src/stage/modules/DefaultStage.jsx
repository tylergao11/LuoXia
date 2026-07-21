/** 通用占位：中心字标 + 标题（地点/情境/入夜等） */
export function DefaultStage({ busy, stageMark, stageTitle, stageHint }) {
  return (
    <div className="stage-module stage-module-default">
      <div className="pull-sheet-stage-glow" />
      <div className={`pull-sheet-stage-mark ${busy ? "pulse" : ""}`}>{stageMark}</div>
      {stageTitle ? <div className="pull-sheet-stage-title">{stageTitle}</div> : null}
      {stageHint ? <div className="pull-sheet-stage-hint">{stageHint}</div> : null}
      {!busy ? <div className="pull-sheet-face-tip">点此切换画面</div> : null}
    </div>
  );
}
