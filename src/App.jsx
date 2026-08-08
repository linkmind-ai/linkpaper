import { useEffect, useRef } from "react";
import AppShell from "./components/Layout/AppShell.jsx";
import Sidebar from "./components/Sidebar/Sidebar.jsx";
import ChatPanel from "./components/Chat/ChatPanel.jsx";
import ToastViewport from "./components/Feedback/ToastViewport.jsx";
import { useChatStore } from "./store/useChatStore.js";
import { useToastStore } from "./store/useToastStore.js";
import { fetchPapers, isMock } from "./api/index.js";

export default function App() {
  const setPapers = useChatStore((s) => s.setPapers);
  const pushToast = useToastStore((s) => s.push);
  const chatPanelRef = useRef(null);

  useEffect(() => {
    fetchPapers()
      .then((papers) => {
        setPapers(papers);
        if (isMock) {
          pushToast({
            variant: "info",
            title: "목업 모드로 실행 중이에요",
            description:
              "백엔드 API 준비 전까지 하드코딩된 데이터로 동작합니다. .env의 VITE_USE_MOCK을 false로 바꾸면 실제 서버를 사용합니다.",
            duration: 5000,
          });
        }
      })
      .catch(() => {
        pushToast({
          variant: "error",
          title: "논문 목록을 불러오지 못했어요",
          description: "잠시 후 새로고침해 다시 시도해주세요.",
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <AppShell
        sidebar={
          <Sidebar
            onPickExample={(text) => chatPanelRef.current?.fillInput(text)}
          />
        }
        main={<ChatPanel ref={chatPanelRef} />}
      />
      <ToastViewport />
    </>
  );
}
