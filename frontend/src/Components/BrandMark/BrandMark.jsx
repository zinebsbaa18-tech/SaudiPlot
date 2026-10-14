import "./BrandMark.css";

export default function BrandMark({ size }) {
  return (
    <span className={`brand-mark${size === "sm" ? " brand-mark--sm" : ""}`} aria-hidden="true">
      ع
    </span>
  );
}
