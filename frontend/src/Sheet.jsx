import { useEffect, useRef, useState } from "react";

/**
 * 居中弹窗：动画面 / 文字面整面点按切换。
 * 默认先显示「画」；右下角翻转标；点遮罩空白关闭。
 */
export function PullSheet({
  open,
  onClose,
  stageMark = "霞",
  stageTitle = "",
  stageHint = "",
  animSlot = "generic",
  busy = false,
  children,
  /** [{ key, label, primary?, danger?, disabled?, onClick }] */
  actions = [],
  dismissible = true,
  /** 默认面：anim=画（默认）| text=文字；忙碌态强制 anim */
  defaultFace = "anim",
}) {
  // 始终默认画；仅显式 defaultFace="text" 且非忙碌时才先出文字
  const resolveFace = () => {
    if (busy) return "anim";
    return defaultFace === "text" ? "text" : "anim";
  };
  const [face, setFace] = useState(resolveFace);
  const dragRef = useRef({ moved: false, y: 0 });
  const textScrollRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setFace(resolveFace());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 打开/标题变化时重置为默认画
  }, [open, defaultFace, stageTitle, busy]);

  useEffect(() => {
    if (!open || face !== "text") return;
    const el = textScrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [open, face, children]);

  if (!open) return null;

  const flip = () => {
    if (busy) return;
    setFace((f) => (f === "anim" ? "text" : "anim"));
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
            data-anim-slot={animSlot}
          >
            <div className="pull-sheet-stage-glow" />
            <div className={`pull-sheet-stage-mark ${busy ? "pulse" : ""}`}>{stageMark}</div>
            {stageTitle ? <div className="pull-sheet-stage-title">{stageTitle}</div> : null}
            {stageHint ? <div className="pull-sheet-stage-hint">{stageHint}</div> : null}
            {!busy ? <div className="pull-sheet-face-tip">点此切换画面</div> : null}
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
