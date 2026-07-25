import PaperSelector from "./PaperSelector.jsx";
import ModeSelector from "./ModeSelector.jsx";
import ExampleQuestions from "./ExampleQuestions.jsx";
import "./sidebar.css";

export default function Sidebar({ onPickExample }) {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__brand-mark">🔗</span>
        <span className="sidebar__brand-name">LinkPaper</span>
      </div>

      <PaperSelector />
      <ModeSelector />
      <ExampleQuestions onPick={onPickExample} />
    </aside>
  );
}
