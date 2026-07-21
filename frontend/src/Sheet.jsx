import { useEffect, useRef, useState } from "react";
import { StageHost } from "./stage/StageHost";

/**
 * 居中弹窗：动画面 / 文字面整面点按切换。
 * 「画」面 = 通用 StageHost 模块槽（交锋/奇遇/武学/…按 moduleId 加载）。
 */
export function PullSheet({
  open,
  onClose,
  stageMark = "霞",
  stageTitle = "",
  stageHint = "",
  /** @deprecated 用 stageModule；仍兼容旧 animSlot */
  animSlot = "generic",
  /** 画模块 id：generic | duel | encounter | arts | … */
  stageModule,
  stageSelf = null,
  stageFoe = null,
  stagePayload = null,
  busy = false,
  children,
  /** [{ key, label, primary?, danger?, disabled?, onClick }] */
  actions = [],
  dismissible = true,
  /** 默认面：anim=画（默认）| text=文字；忙碌态强制 anim */
  defaultFace = "anim",
  /** 受控面；传入则由父组件决定当前面 */
  face: faceProp,
  onFaceChange,
}) {
  const moduleId = stageModule || animSlot || "generic";
  const resolveFace = () => {
    if (busy) return "anim";
    return defaultFace === "text" ? "text" : "anim";
  };
  const [innerFace, setInnerFace] = useState(resolveFace);
  const controlled = faceProp === "anim" || faceProp === "text";
  const face = busy ? "anim" : controlled ? faceProp : innerFace;
  const dragRef = useRef({ moved: false, y: 0 });
  const textScrollRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    if (!controlled) setInnerFace(resolveFace());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 打开/标题变化时重置为默认画
  }, [open, defaultFace, stageTitle, busy, controlled]);

  useEffect(() => {
    if (!open || face !== "text") return;
    const el = textScrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = 0;
    });
  }, [open, face, children]);

  if (!open) return null;

  const setFace = (next) => {
    if (busy) return;
    const value = typeof next === "function" ? next(face) : next;
    if (controlled) onFaceChange?.(value);
    else setInnerFace(value);
  };

  const flip = () => {
    if (busy) return;
    setFace(face === "anim" ? "text" : "anim");
  };

  return (
    <div
      className={`pull-sheet-backdrop ${busy ? "busy" : ""}`}
      onClick={() => {
        if (dismissible) onClose?.();
      }}
    >
      <div
        className={`pull-sheet face-${face}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={stageTitle || "卷"}
      >
        <div
          className="pull-sheet-flip-area"
          onPointerDown={(e) => {
            dragRef.current = { moved: false, y: e.clientY };
          }}
          onPointerMove={(e) => {
            if (Math.abs(e.clientY - dragRef.current.y) > 10) {
              dragRef.current.moved = true;
            }
          }}
          onClick={() => {
            if (!dragRef.current.moved) flip();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              flip();
            }
          }}
          role="button"
          tabIndex={0}
          aria-label={face === "anim" ? "点按查看文字" : "点按查看动画"}
        >
          <div
            className={`pull-sheet-face pull-sheet-face-anim ${face === "anim" ? "active" : ""}`}
            data-anim-slot={moduleId}
            data-stage-module={moduleId}
          >
            <StageHost
              moduleId={moduleId}
              busy={busy}
              stageMark={stageMark}
              stageTitle={stageTitle}
              stageHint={stageHint}
              stageSelf={stageSelf}
              stageFoe={stageFoe}
              stagePayload={stagePayload}
            />
          </div>

          <div
            className={`pull-sheet-face pull-sheet-face-text ${face === "text" ? "active" : ""}`}
          >
            {stageTitle ? <div className="pull-sheet-text-head">{stageTitle}</div> : null}
            <div ref={textScrollRef} className="pull-sheet-text-scroll scroll-y">
              {children}
            </div>
          </div>

          {!busy ? (
            <div className="pull-sheet-flip-badge" aria-hidden>
              {face === "anim" ? "文" : "画"}
              <span className="pull-sheet-flip-icon">⇄</span>
            </div>
          ) : null}
        </div>

        {actions?.length > 0 && (
          <div className="pull-sheet-actions" onClick={(e) => e.stopPropagation()}>
            {actions.map((a) => (
              <button
                key={a.key || a.label}
                type="button"
                className={
                  a.primary
                    ? "sheet-btn sheet-btn-primary"
                    : a.danger
                      ? "sheet-btn sheet-btn-danger"
                      : "sheet-btn sheet-btn-ghost"
                }
                disabled={a.disabled}
                onClick={a.onClick}
              >
                {a.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
