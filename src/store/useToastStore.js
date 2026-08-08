import { create } from "zustand";

let idCounter = 0;

export const useToastStore = create((set) => ({
  toasts: [],
  push: (toast) => {
    const id = ++idCounter;
    const entry = {
      id,
      variant: toast.variant || "info", // "info" | "error" | "success"
      title: toast.title,
      description: toast.description,
      duration: toast.duration ?? 4000,
    };
    set((state) => ({ toasts: [...state.toasts, entry] }));
    if (entry.duration) {
      setTimeout(() => {
        set((state) => ({
          toasts: state.toasts.filter((t) => t.id !== id),
        }));
      }, entry.duration);
    }
    return id;
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));
