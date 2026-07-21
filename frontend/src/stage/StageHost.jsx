import { resolveStageModule } from "./registry";

/**
 * 弹窗动画面宿主：按 moduleId 热切换表现模块。
 * 模块自己决定布局（交锋左下/右上、奇遇、武学…）；宿主不写死玩法。
 */
export function StageHost({
  moduleId = "generic",
  busy = false,
  stageMark = "霞",
  stageTitle = "",
  stageHint = "",
  stageSelf = null,
  stageFoe = null,
  stagePayload = null,
}) {
  const Mod = resolveStageModule(moduleId);
  return (
    <div className="stage-host" data-stage-module={moduleId || "generic"}>
      <Mod
        busy={busy}
        stageMark={stageMark}
        stageTitle={stageTitle}
        stageHint={stageHint}
        stageSelf={stageSelf}
        stageFoe={stageFoe}
        stagePayload={stagePayload}
      />
    </div>
  );
}
