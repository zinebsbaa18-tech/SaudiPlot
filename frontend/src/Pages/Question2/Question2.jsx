import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QuestionLayout from "../../Components/QuestionLayout/QuestionLayout";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";

export default function Question2() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const hasElderly = useFormStore((state) => state.hasElderly);
  const setHasElderly = useFormStore((state) => state.setHasElderly);

  return (
    <QuestionLayout
      stepIndex={2}
      stepLabel={t("q2.step")}
      title={t("q2.title")}
      subtitle={t("q2.subtitle")}
      onBack={() => navigate(-1)}
      onNext={() => {
        useFormStore.getState().saveBriefToBackend().catch(() => {});
        navigate("/questions/3");
      }}
    >
      <div className="chip-row">
        <button
          type="button"
          className={`chip ${hasElderly ? "chip--selected" : ""}`}
          onClick={() => setHasElderly(true)}
        >
          {t("q2.yes")}
        </button>
        <button
          type="button"
          className={`chip ${!hasElderly ? "chip--selected" : ""}`}
          onClick={() => setHasElderly(false)}
        >
          {t("q2.no")}
        </button>
      </div>
    </QuestionLayout>
  );
}
