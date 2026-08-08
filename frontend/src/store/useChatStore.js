import { create } from "zustand";
import { streamChat } from "../api/index.js";
import { useToastStore } from "./useToastStore.js";

let msgIdCounter = 0;
const nextId = () => `m-${++msgIdCounter}`;

export const useChatStore = create((set, get) => ({
  papers: [],
  selectedPaperId: null,
  mode: "paper-qa",
  messagesByMode: {
    "paper-qa": [],
    "graph-rag-qa": [],
    "research-flow": [],
  },
  isStreaming: false,
  abortController: null,

  setPapers: (papers) =>
    set({ papers, selectedPaperId: papers[0]?.id ?? null }),

  selectPaper: (paperId) => set({ selectedPaperId: paperId }),

  setMode: (mode) => set({ mode }),

  currentMessages: () => get().messagesByMode[get().mode] ?? [],

  clearCurrentThread: () =>
    set((state) => ({
      messagesByMode: { ...state.messagesByMode, [state.mode]: [] },
    })),

  sendMessage: async (text) => {
    const trimmed = text.trim();
    if (!trimmed || get().isStreaming) return;

    const { mode, selectedPaperId } = get();
    const userMsg = { id: nextId(), role: "user", content: trimmed };
    const assistantMsg = {
      id: nextId(),
      role: "assistant",
      content: "",
      citations: [],
      flow: null,
      status: "streaming", // "streaming" | "done" | "error"
    };

    set((state) => ({
      messagesByMode: {
        ...state.messagesByMode,
        [mode]: [...state.messagesByMode[mode], userMsg, assistantMsg],
      },
      isStreaming: true,
    }));

    const abortController = new AbortController();
    set({ abortController });

    const updateAssistant = (patch) => {
      set((state) => ({
        messagesByMode: {
          ...state.messagesByMode,
          [mode]: state.messagesByMode[mode].map((m) =>
            m.id === assistantMsg.id ? { ...m, ...patch } : m
          ),
        },
      }));
    };

    try {
      const history = get().messagesByMode[mode].filter(
        (m) => m.status !== "streaming"
      );

      for await (const event of streamChat({
        paperId: selectedPaperId,
        mode,
        message: trimmed,
        history,
        signal: abortController.signal,
      })) {
        const current = get().messagesByMode[mode].find(
          (m) => m.id === assistantMsg.id
        );
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
