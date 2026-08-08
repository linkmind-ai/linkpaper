import { X, AlertCircle, CheckCircle2, Info } from "lucide-react";
import { useToastStore } from "../../store/useToastStore.js";
import "./toast.css";

const ICONS = {
  info: Info,
  error: AlertCircle,
  success: CheckCircle2,
};

export default function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-viewport" role="region" aria-live="polite">
      {toasts.map((toast) => {
        const Icon = ICONS[toast.variant] || Info;
        return (
          <div key={toast.id} className={`toast toast--${toast.variant}`}>
            <div className="toast__header">
              <Icon size={15} strokeWidth={2.25} />
              <span>{toast.title}</span>
              <button
                className="toast__close"
                onClick={() => dismiss(toast.id)}
                aria-label="알림 닫기"
              >
                <X size={14} />
              </button>
            </div>
            {toast.description && (
              <div className="toast__body">{toast.description}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
