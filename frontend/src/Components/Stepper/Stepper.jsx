import "./Stepper.css";

export default function Stepper({ label, value, onChange, min = 0, max = 20, badge }) {
  return (
    <div className="stepper-row">
      <div className="stepper-row__label-group">
        <p className="stepper-row__label">{label}</p>
        {badge && <span className="stepper-row__badge">{badge}</span>}
      </div>
      <div className="stepper-row__controls">
        <button
          type="button"
          className="stepper-btn"
          onClick={() => onChange(Math.max(min, value - 1))}
          disabled={value <= min}
          aria-label="تقليل"
        >
          −
        </button>
        <span className="stepper-row__value">{value}</span>
        <button
          type="button"
          className="stepper-btn"
          onClick={() => onChange(Math.min(max, value + 1))}
          disabled={value >= max}
          aria-label="زيادة"
        >
          +
        </button>
      </div>
    </div>
  );
}
