/**
 * 对峙位：己方左下、对方/客体右上。
 * 各玩法模块可复用，也可自绘。
 */
export function StageMounts({
  selfMark = "我",
  selfLabel = "",
  foeMark = "对方",
  foeLabel = "",
  busy = false,
}) {
  return (
    <>
      <div className="stage-mount stage-mount-foe" aria-label={foeLabel || "对方"}>
        <div className={`stage-mount-mark ${busy ? "pulse" : ""}`}>{foeMark}</div>
        {foeLabel ? <div className="stage-mount-label">{foeLabel}</div> : null}
      </div>
      <div className="stage-mount stage-mount-self" aria-label={selfLabel || "己方"}>
        <div className={`stage-mount-mark ${busy ? "pulse" : ""}`}>{selfMark}</div>
        {selfLabel ? <div className="stage-mount-label">{selfLabel}</div> : null}
      </div>
    </>
  );
}

export function StageCaption({ title = "", hint = "", tip = "" }) {
  return (
    <div className="stage-caption">
      {title ? <div className="pull-sheet-stage-title">{title}</div> : null}
      {hint ? <div className="pull-sheet-stage-hint">{hint}</div> : null}
      {tip ? <div className="pull-sheet-face-tip">{tip}</div> : null}
    </div>
  );
}
