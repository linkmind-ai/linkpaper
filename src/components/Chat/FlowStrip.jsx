import "./chat.css";

export default function FlowStrip({ flow }) {
  if (!flow?.length) return null;

  return (
    <div className="flow-strip">
      {flow.map((node, i) => (
        <div className="flow-strip__node-wrap" key={node.stage}>
          <div
            className={`flow-strip__node ${
              node.stage === "현재 논문" ? "is-current" : ""
            }`}
          >
            <span className="flow-strip__stage">{node.stage}</span>
            <span className="flow-strip__label">{node.label}</span>
          </div>
          {i < flow.length - 1 && <div className="flow-strip__connector" />}
        </div>
      ))}
    </div>
  );
}
