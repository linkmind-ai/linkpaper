import ResizeHandle from "./ResizeHandle.jsx";
import "./layout.css";

export default function AppShell({
  sidebar,
  paperViewer,
  chat,
  sidebarWidth,
  paperWidth,
  onSidebarHandleMouseDown,
  onPaperHandleMouseDown,
}) {
  return (
    <div className="app-shell">
      <div className="app-shell__pane" style={{ width: sidebarWidth, flex: "0 0 auto" }}>
        {sidebar}
      </div>

      <ResizeHandle onMouseDown={onSidebarHandleMouseDown} label="사이드바 너비 조절" />

      <div className="app-shell__pane" style={{ width: paperWidth, flex: "0 0 auto" }}>
        {paperViewer}
      </div>

      <ResizeHandle onMouseDown={onPaperHandleMouseDown} label="논문 뷰어 너비 조절" />

      <div className="app-shell__pane app-shell__pane--fill">{chat}</div>
    </div>
  );
}
