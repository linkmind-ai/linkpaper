import { useEffect, useRef } from "react";
import AppShell from "./components/Layout/AppShell.jsx";
import Sidebar from "./components/Sidebar/Sidebar.jsx";
import ChatPanel from "./components/Chat/ChatPanel.jsx";
import PaperViewer from "./components/PaperViewer/PaperViewer.jsx";
import ToastViewport from "./components/Feedback/ToastViewport.jsx";
import { useToastStore } from "./store/useToastStore.js";
import { useResizablePanels } from "./hooks/useResizablePanels.js";
import { isMock } from "./api/index.js";

export default function App() {
  const pushToast = useToastStore((s) => s.push);
  const chatPanelRef = useRef(null);
  const notifiedRef = useRef(false);
  const {
    sidebarWidth,
    paperWidth,
    onSidebarHandleMouseDown,
    onPaperHandleMouseDown,
  } = useResizablePanels();

  useEffect(() => {
    if (isMock && !notifiedRef.current) {
      notifiedRef.current = true;
      pushToast({
        variant: "info",
        title: "목업 모드로 실행 중이에요",
        description:
          "arXiv 검색과 백엔드 API 준비 전까지 하드코딩된 데이터로 동작합니다. .env의 VITE_USE_MOCK을 false로 바꾸면 실제 서버를 사용합니다.",
        duration: 5000,
      });
    }
  }, [pushToast]);

  return (
    <>
      <AppShell
        sidebar={
          <Sidebar
            onPickExample={(text) => chatPanelRef.current?.fillInput(text)}
          />
        }
        paperViewer={<PaperViewer />}
        chat={<ChatPanel ref={chatPanelRef} />}
        sidebarWidth={sidebarWidth}
        paperWidth={paperWidth}
        onSidebarHandleMouseDown={onSidebarHandleMouseDown}
        onPaperHandleMouseDown={onPaperHandleMouseDown}
      />
      <ToastViewport />
    </>
  );
}
