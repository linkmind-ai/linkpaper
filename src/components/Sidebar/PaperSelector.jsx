import { FileText, ChevronDown } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { useChatStore } from "../../store/useChatStore.js";
import "./sidebar.css";

export default function PaperSelector() {
  const papers = useChatStore((s) => s.papers);
  const selectedPaperId = useChatStore((s) => s.selectedPaperId);
  const selectPaper = useChatStore((s) => s.selectPaper);
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  const selected = papers.find((p) => p.id === selectedPaperId);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div className="paper-selector" ref={rootRef}>
      <span className="sidebar-label">선택한 논문</span>
      <button
        className="paper-selector__trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <FileText size={16} />
        <span className="paper-selector__title">
          {selected ? selected.title : "논문을 선택하세요"}
        </span>
        <ChevronDown size={16} className={open ? "rotate" : ""} />
      </button>

      {open && (
        <div className="paper-selector__menu" role="listbox">
          {papers.map((paper) => (
            <button
              key={paper.id}
              role="option"
              aria-selected={paper.id === selectedPaperId}
              className={`paper-selector__item ${
                paper.id === selectedPaperId ? "is-active" : ""
              }`}
              onClick={() => {
                selectPaper(paper.id);
                setOpen(false);
              }}
            >
              <div className="paper-selector__item-title">{paper.title}</div>
              <div className="paper-selector__item-meta">
                {paper.authors} · {paper.year}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
