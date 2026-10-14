import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QuestionLayout from "../../Components/QuestionLayout/QuestionLayout";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";

const OPTIONS = ["مفتوح على الصالة", "مغلق", "مغلق + مطبخ تحضيري"];

export default function Question4() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const selected = useFormStore((state) => state.kitchenType);
  const setSelected = useFormStore((state) => state.setKitchenType);

  return (
    <QuestionLayout
      stepIndex={4}
      stepLabel={t("q4.step")}
      title={t("q4.title")}
      subtitle={t("q4.subtitle")}
      onBack={() => navigate(-1)}
      onNext={() => {
        useFormStore.getState().saveBriefToBackend().catch(() => {});
        navigate("/questions/5");
      }}
    >
      <div className="chip-row">
        {OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            className={`chip ${selected === option ? "chip--selected" : ""}`}
            onClick={() => setSelected(option)}
          >
            {t(option === "مفتوح على الصالة" ? "q4.open" : option === "مغلق" ? "q4.closed" : "q4.closed_prep")}
          </button>
        ))}
      </div>
    </QuestionLayout>
  );
}
