import { StageCaption, StageMounts } from "./StageMounts";

/** 武学/功法展示模块占位：左下修士、右上功法。 */
export function GongfaStage({
  busy = false,
  stageMark = "法",
  stageTitle = "",
  stageHint = "",
  selfMark = "修",
  selfLabel = "修士",
  foeMark,
  foeLabel = "功法",
}) {
  return (
    <div className="stage-module stage-module-gongfa">
      <div className="pull-sheet-stage-glow" />
      <StageMounts
        busy={busy}
        selfMark={selfMark}
        selfLabel={selfLabel}
        foeMark={foeMark || stageMark}
        foeLabel={foeLabel}
      />
      <StageCaption
        title={stageTitle || "功法"}
        hint={stageHint || "新得之术"}
        tip={busy ? "" : "点此切换画面"}
      />
    </div>
  );
}
