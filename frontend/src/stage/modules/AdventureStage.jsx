import { StageCaption, StageMounts } from "./StageMounts";

/** 奇遇模块占位：左下行者、右上机缘。 */
export function AdventureStage({
  busy = false,
  stageMark = "奇",
  stageTitle = "",
  stageHint = "",
  selfMark = "行",
  selfLabel = "行者",
  foeMark = "缘",
  foeLabel = "机缘",
}) {
  return (
    <div className="stage-module stage-module-adventure">
      <div className="pull-sheet-stage-glow" />
      <StageMounts
        busy={busy}
        selfMark={selfMark}
        selfLabel={selfLabel}
        foeMark={foeMark || stageMark}
        foeLabel={foeLabel}
      />
      <StageCaption
        title={stageTitle || "奇遇"}
        hint={stageHint || "机缘当前"}
        tip={busy ? "" : "点此切换画面"}
      />
    </div>
  );
}
