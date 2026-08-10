import { useEffect, useState, useRef } from "react";
import { Search, Loader2, FileText } from "lucide-react";
import { useChatStore } from "../../store/useChatStore.js";
import "./sidebar.css";

export default function ArxivSearch() {
  const [input, setInput] = useState("");
  const papers = useChatStore((s) => s.papers);
  const selectedPaper = useChatStore((s) => s.selectedPaper);
  const isSearching = useChatStore((s) => s.isSearching);
  const runSearch = useChatStore((s) => s.runSearch);
  const selectPaper = useChatStore((s) => s.selectPaper);
  const debounceRef = useRef(null);

  // 최초 진입 시 기본 목록을 한 번 불러옵니다.
  useEffect(() => {
    runSearch("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleChange = (e) => {
    const value = e.target.value;
    setInput(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(value), 350);
  };

  return (
    <div className="arxiv-search">
      <span className="sidebar-label">arXiv 논문 검색</span>

      <div className="arxiv-search__input-wrap">
        <Search size={15} className="arxiv-search__icon" />
        <input
          className="arxiv-search__input"
          placeholder="제목, 저자, arXiv ID로 검색"
          value={input}
          onChange={handleChange}
        />
        {isSearching && (
          <Loader2 size={14} className="arxiv-search__spinner" />
        )}
      </div>

      <div className="arxiv-search__results">
        {!isSearching && papers.length === 0 && (
          <p className="arxiv-search__empty">검색 결과가 없습니다.</p>
        )}
        {papers.map((paper) => (
          <button
            key={paper.id}
            className={`arxiv-result ${
              paper.id === selectedPaper?.id ? "is-active" : ""
            }`}
            onClick={() => selectPaper(paper)}
          >
            <FileText size={14} className="arxiv-result__icon" />
            <div className="arxiv-result__body">
              <div className="arxiv-result__title">{paper.title}</div>
              <div className="arxiv-result__meta">
                {paper.authors} · {paper.year} · arXiv:{paper.id}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
