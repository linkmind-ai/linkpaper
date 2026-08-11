import "./layout.css";

export default function ResizeHandle({ onMouseDown, label }) {
  return (
    <div
      className="resize-handle"
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
    >
      <div className="resize-handle__grip" />
    </div>
  );
}
