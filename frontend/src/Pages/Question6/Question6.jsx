import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QuestionLayout from "../../Components/QuestionLayout/QuestionLayout";
import usePageTitle from "../../hooks/usePageTitle";
import "./Question6.css";

const TAGS = [
  { labelKeys: ["room_catalog.master"], size: "28", color: "pink" },
  { labelKeys: ["room_catalog.bedroom"], count: "3", size: "46", color: "green" },
  { labelKeys: ["room_catalog.bathroom"], count: "3", size: "19", color: "purple" },
  { labelKeys: ["room_catalog.living"], size: "38", color: "gray" },
  { labelKeys: ["room_catalog.prep_kitchen"], size: "28", color: "yellow" },
  { labelKeys: ["room_catalog.majlis", "room_catalog.dining"], size: "46", color: "blue" },
  { labelKeys: ["room_catalog.guest_bath"], size: "5", color: "purple" },
  { labelKeys: ["room_catalog.driver_room"], size: "24", color: "blue" },
  { labelKeys: ["room_catalog.laundry"], size: "8", color: "gray" },
];

function tagLabel(t, i18n, tag) {
  const name = tag.labelKeys.map((k) => t(k)).join(" + ");
  const count = tag.count ? ` ×${tag.count}` : "";
  const unit = i18n.language === "ar" ? "م²" : "m²";
  return `${name}${count} · ${tag.size}${unit}`;
}

export default function Question6() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  return (
    <QuestionLayout
      stepIndex={6}
      stepLabel={t("q6.step")}
      title={t("q6.title")}
      subtitle={t("q6.subtitle")}
      onBack={() => navigate(-1)}
      onNext={() => navigate("/generating")}
      nextLabel={t("q6.next")}
      singleAction
    >
      <div className="space-tags">
        {TAGS.map((tag) => (
          <span key={tag.labelKeys[0]} className={`space-tag space-tag--${tag.color}`}>
            {tagLabel(t, i18n, tag)}
          </span>
        ))}
      </div>

      <button type="button" className="space-edit-btn" onClick={() => navigate("/room-catalog")}>
        {/* DOM order (text, icon) so RTL flex places the text at the visual
            right and the pencil icon at the visual left, matching the design. */}
        {t("q6.edit")}
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
          <path
            d="M4 20l1.1-4.4L16.5 4.2a1.5 1.5 0 0 1 2.1 0l1.2 1.2a1.5 1.5 0 0 1 0 2.1L8.4 18.9 4 20Z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      <p className="space-summary">{t("q6.summary")}</p>
    </QuestionLayout>
  );
}
