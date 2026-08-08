import "./layout.css";

export default function AppShell({ sidebar, main }) {
  return (
    <div className="app-shell">
      {sidebar}
      {main}
    </div>
  );
}
