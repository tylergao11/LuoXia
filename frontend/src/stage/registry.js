import { DefaultStage } from "./modules/DefaultStage";
import { DuelStage } from "./modules/DuelStage";
import { EncounterStage } from "./modules/EncounterStage";
import { ArtsStage } from "./modules/ArtsStage";

/**
 * 弹窗「画」面模块注册表。
 * 战斗 / 奇遇 / 武学 / 其它乱七八糟 → 都挂这里，PullSheet 只按 id 加载。
 */
const REGISTRY = {
  generic: DefaultStage,
  tiandao: DefaultStage,
  location: DefaultStage,
  actor: DefaultStage,
  status: DefaultStage,
  beliefs: DefaultStage,
  clues: DefaultStage,
  duel: DuelStage,
  combat: DuelStage,
  encounter: EncounterStage,
  adventure: EncounterStage,
  arts: ArtsStage,
  gongfa: ArtsStage,
};

export function resolveStageModule(moduleId) {
  const key = String(moduleId || "generic").trim() || "generic";
  return REGISTRY[key] || DefaultStage;
}

export function listStageModules() {
  return Object.keys(REGISTRY);
}
