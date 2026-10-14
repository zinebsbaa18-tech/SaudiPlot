import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QuestionLayout from "../../Components/QuestionLayout/QuestionLayout";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";

const ROW_1 = ["غسيل وكيّ", "غرفة عاملة منزلية بحمّام", "غرفة سائق بحمّام"];
const ROW_2 = ["لا شيء", "مدخل خدمة مستقل", "مستودع"];

export default function Question5() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const selected = useFormStore((state) => state.services);
  const setServices = useFormStore((state) => state.setServices);

  function toggle(option) {
    setServices(
      selected.includes(option)
        ? selected.filter((item) => item !== option)
        : [...selected, option]
    );
  }

  const optionLabel = {
    "غسيل وكيّ": t("q5.laundry"),
    "غرفة عاملة منزلية بحمّام": t("q5.maid"),
    "غرفة سائق بحمّام": t("q5.driver"),
    "لا شيء": t("q5.none"),
    "مدخل خدمة مستقل": t("q5.service_entrance"),
    "مستودع": t("q5.storage"),
  };

  function renderChip(option) {
    const isSelected = selected.includes(option);
    const label = optionLabel[option] || option;
    return (
      <button
        key={option}
        type="button"
        className={`chip ${isSelected ? "chip--selected" : ""}`}
        onClick={() => toggle(option)}
      >
        {isSelected ? `${label} ✓` : label}
      </button>
    );
  }

  return (
    <QuestionLayout
      stepIndex={5}
      stepLabel={t("q5.step")}
      title={t("q5.title")}
      subtitle={t("q5.subtitle")}
      onBack={() => navigate(-1)}
      onNext={() => {
        useFormStore.getState().saveBriefToBackend().catch(() => {});
        navigate("/questions/6");
      }}
    >
      <div className="stepper-stack">
        <div className="chip-row">{ROW_1.map(renderChip)}</div>
        <div className="chip-row">{ROW_2.map(renderChip)}</div>
      </div>
    </QuestionLayout>
  );
}
