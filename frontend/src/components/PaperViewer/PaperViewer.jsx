import { useState } from "react";
import {
  ExternalLink,
  FileDown,
  BookOpen,
  FileType,
  ChevronUp,
  ChevronDown,
} from "lucide-react";
import { useChatStore } from "../../store/useChatStore.js";
import "./paperViewer.css";

export default function PaperViewer() {
  const paper = useChatStore((s) => s.selectedPaper);
  const [tab, setTab] = useState("abstract"); // "abstract" | "pdf"
  const [headerCollapsed, setHeaderCollapsed] = useState(false);

  if (!paper) {
    return (
      <section className="paper-viewer">
        <div className="paper-viewer__empty">
          <BookOpen size={28} />
          <p>왼쪽에서 arXiv 논문을 검색하고 선택하면 여기에 표시됩니다.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="paper-viewer">
      {headerCollapsed ? (
        // 접힌 상태: 제목 한 줄 + 펼치기 버튼만 남겨서 본문 영역을 최대한 확보
        <button
          className="paper-viewer__header-collapsed"
          onClick={() => setHeaderCollapsed(false)}
        >
          <span className="paper-viewer__arxiv-id">arXiv:{paper.id}</span>
          <span className="paper-viewer__header-collapsed-title">
            {paper.title}
          </span>
          <span className="paper-viewer__collapse-toggle">
            <ChevronDown size={15} />
          </span>
        </button>
      ) : (
        <header className="paper-viewer__header">
          <button
            className="paper-viewer__collapse-toggle paper-viewer__collapse-toggle--floating"
            onClick={() => setHeaderCollapsed(true)}
            title="논문 정보 접기"
            aria-label="논문 정보 접기"
          >
            <ChevronUp size={15} />
          </button>

          <div className="paper-viewer__badges">
            <span className="paper-viewer__arxiv-id">arXiv:{paper.id}</span>
            {paper.categories?.map((cat) => (
              <span key={cat} className="paper-viewer__category">
                {cat}
              </span>
            ))}
          </div>
          <h1 className="paper-viewer__title">{paper.title}</h1>
          <p className="paper-viewer__meta">
            {paper.authors} · {paper.year}
          </p>

          <div className="paper-viewer__actions">
            <a
              className="paper-viewer__action-btn"
              href={paper.arxivUrl}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={13} />
              arXiv에서 보기
            </a>
            <a
              className="paper-viewer__action-btn"
              href={paper.pdfUrl}
              target="_blank"
              rel="noreferrer"
            >
              <FileDown size={13} />
              PDF 새 탭에서 열기
            </a>
          </div>
        </header>
      )}

      <div className="paper-viewer__tabs">
        <button
          className={`paper-viewer__tab ${tab === "abstract" ? "is-active" : ""}`}
          onClick={() => setTab("abstract")}
        >
          <BookOpen size={13} />
          초록
        </button>
        <button
          className={`paper-viewer__tab ${tab === "pdf" ? "is-active" : ""}`}
          onClick={() => setTab("pdf")}
        >
          <FileType size={13} />
          PDF 미리보기
        </button>
      </div>

      <div className="paper-viewer__body">
        {tab === "abstract" ? (
          <p className="paper-viewer__abstract">{paper.summary}</p>
        ) : (
          <div className="paper-viewer__pdf-wrap">
            <iframe
              key={paper.id}
              src={paper.pdfUrl}
              title={`${paper.title} PDF`}
              className="paper-viewer__pdf-frame"
            />
            <p className="paper-viewer__pdf-fallback">
              미리보기가 보이지 않으면{" "}
              <a href={paper.pdfUrl} target="_blank" rel="noreferrer">
                여기를 눌러 새 탭에서 열어주세요
              </a>
              .
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
