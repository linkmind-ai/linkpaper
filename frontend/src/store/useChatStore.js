import { create } from "zustand";
import { streamChat, searchPapers } from "../api/index.js";
import { useToastStore } from "./useToastStore.js";

let msgIdCounter = 0;
const nextId = () => `m-${++msgIdCounter}`;

// 백엔드가 단일 파이프라인 안에서 질문을 라우팅하므로, 프론트엔드에도
// 기능/모드 구분이 없는 단일 대화 스레드만 존재합니다.
export const useChatStore = create((set, get) => ({
  // --- arXiv 검색 / 논문 뷰어 ---
  papers: [], // 최근 검색 결과
  selectedPaper: null,
  searchQuery: "",
  isSearching: false,

  // --- 채팅 (단일 스레드) ---
  messages: [],
  isStreaming: false,
  abortController: null,

  runSearch: async (query) => {
    set({ isSearching: true, searchQuery: query });
    try {
      const results = await searchPapers(query);
      set((state) => ({
        papers: results,
        // 검색 결과가 바뀌어도 이미 선택된 논문이 결과 안에 있으면 유지
        selectedPaper:
          results.find((p) => p.id === state.selectedPaper?.id) ??
          results[0] ??
          state.selectedPaper,
      }));
    } catch (err) {
      useToastStore.getState().push({
        variant: "error",
        title: "arXiv 검색에 실패했어요",
        description: "잠시 후 다시 시도해주세요.",
      });
      console.error(err);
    } finally {
      set({ isSearching: false });
    }
  },

  selectPaper: (paper) => set({ selectedPaper: paper }),

  clearThread: () => set({ messages: [] }),

  sendMessage: async (text) => {
    const trimmed = text.trim();
    if (!trimmed || get().isStreaming) return;

    const { selectedPaper } = get();
    if (!selectedPaper) {
      useToastStore.getState().push({
        variant: "error",
        title: "논문을 먼저 선택해주세요",
        description: "왼쪽 검색 결과에서 질문할 논문을 선택할 수 있어요.",
      });
      return;
    }

    const userMsg ={ id: nextId(), role: "user", content: trimmed };
    const assistantMsg = {
      id: nextId(),
      role: "assistant",
      content: "",
      citations: [],
      flow: null,
      status: "streaming", // "streaming" | "done" | "error"
    };

    set((state) => ({
      messages: [...state.messages, userMsg, assistantMsg],
      isStreaming: true,
    }));

    const abortController = new AbortController();
    set({ abortController });

    const updateAssistant = (patch) => {
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === assistantMsg.id ? { ...m, ...patch } : m
        ),
      }));
    };

    try {
      // 실패해 내용이 비어 있는 답변은 모델 입력에서 제외합니다.
      const history = get()
        .messages.filter((m) => m.status !== "streaming" && m.content)
        .map(({ role, content }) => ({ role, content }));

      for await (const event of streamChat({
        paperId: selectedPaper.id,
        message: trimmed,
        history,
        signal: abortController.signal,
      })) {
        const current = get().messages.find((m) => m.id === assistantMsg.id);
        if (!current) break;

        if (event.type === "token") {
          updateAssistant({ content: current.content + event.text });
        } else if (event.type === "citations") {
          updateAssistant({ citations: event.citations });
        } else if (event.type === "flow") {
          updateAssistant({ flow: event.flow });
        } else if (event.type === "error") {
          updateAssistant({ status: "error" });
          useToastStore.getState().push({
            variant: "error",
            title: "응답을 가져오지 못했어요",
            description: event.message || "잠시 후 다시 시도해주세요.",
          });
        } else if (event.type === "done") {
          updateAssistant({ status: "done" });
        }
      }
    } catch (err) {
      // 사용자가 중지한 경우는 오류가 아니므로 받은 내용까지만 남깁니다.
      if (err.name === "AbortError") {
        updateAssistant({ status: "done" });
        return;
      }
      updateAssistant({ status: "error" });
      useToastStore.getState().push({
        variant: "error",
        title: "연결에 문제가 발생했어요",
        description: "네트워크 상태를 확인한 뒤 다시 시도해주세요.",
      });
      console.error(err);
    } finally {
      set({ isStreaming: false, abortController: null });
    }
  },

  stopStreaming: () => {
    get().abortController?.abort();
  },
}));
