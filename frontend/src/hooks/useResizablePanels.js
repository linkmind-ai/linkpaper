import { useCallback, useRef, useState } from "react";

const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 440;
const SIDEBAR_DEFAULT = 300;

const PAPER_MIN = 380;
const PAPER_MAX_MARGIN = 420; // 채팅 패널을 위해 항상 남겨둘 최소 여유 공간
const PAPER_DEFAULT = 760;

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

// 좌측 사이드바 ↔ 논문 뷰어, 논문 뷰어 ↔ 채팅 패널 사이의 드래그 리사이즈를 관리합니다.
// 채팅 패널은 flex:1로 나머지 공간을 그대로 채우므로 별도 width 상태가 필요 없습니다.
export function useResizablePanels() {
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [paperWidth, setPaperWidth] = useState(PAPER_DEFAULT);
  const dragState = useRef(null);

  const startDrag = useCallback(
    (target) => (e) => {
      dragState.current = {
        target,
        startX: e.clientX,
        startSidebar: sidebarWidth,
        startPaper: paperWidth,
      };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const handleMove = (moveEvent) => {
        if (!dragState.current) return;
        const delta = moveEvent.clientX - dragState.current.startX;

        if (dragState.current.target === "sidebar") {
          setSidebarWidth(
            clamp(dragState.current.startSidebar + delta, SIDEBAR_MIN, SIDEBAR_MAX)
          );
        } else {
          const maxPaper =
            window.innerWidth - sidebarWidth - PAPER_MAX_MARGIN;
          setPaperWidth(
            clamp(dragState.current.startPaper + delta, PAPER_MIN, Math.max(PAPER_MIN, maxPaper))
          );
        }
      };

      const handleUp = () => {
        dragState.current = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("mousemove", handleMove);
        window.removeEventListener("mouseup", handleUp);
      };

      window.addEventListener("mousemove", handleMove);
      window.addEventListener("mouseup", handleUp);
    },
    [sidebarWidth, paperWidth]
  );

  return {
    sidebarWidth,
    paperWidth,
    onSidebarHandleMouseDown: startDrag("sidebar"),
    onPaperHandleMouseDown: startDrag("paper"),
  };
}
