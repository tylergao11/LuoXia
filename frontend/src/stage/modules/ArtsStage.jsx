/** 武学/功法阁模块占位：展示未知功法皮，骨在服务端校验 */
export function ArtsStage({ busy, stageMark, stageTitle, stageHint }) {
  return (
    <div className="stage-module stage-module-arts">
      <div className="pull-sheet-stage-glow" />
      <div className="stage-arts-badge">武学</div>
      <div className={`pull-sheet-stage-mark ${busy ? "pulse" : ""}`}>{stageMark || "功"}</div>
      {stageTitle ? <div className="pull-sheet-stage-title">{stageTitle}</div> : null}
      {stageHint ? <div className="pull-sheet-stage-hint">{stageHint}</div> : null}
      {!busy ? <div className="pull-sheet-face-tip">点此切换画面</div> : null}
    </div>
  );
}
