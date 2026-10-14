import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QuestionLayout from "../../Components/QuestionLayout/QuestionLayout";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";

export default function Question3() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const OPTIONS = [
    {
      id: "independent",
      title: t("q3.option1"),
      desc: t("q3.desc1"),
    },
    {
      id: "split",
      title: t("q3.option2"),
      desc: t("q3.desc2"),
    },
    {
      id: "living-room",
      title: t("q3.option3"),
      desc: t("q3.desc3"),
    },
  ];
  const selected = useFormStore((state) => state.guestReceptionId);
  const setSelected = useFormStore((state) => state.setGuestReceptionId);

  return (
    <QuestionLayout
      stepIndex={3}
      stepLabel={t("q3.step")}
      title={t("q3.title")}
      subtitle={t("q3.subtitle")}
      onBack={() => navigate(-1)}
      onNext={() => {
        useFormStore.getState().saveBriefToBackend().catch(() => {});
        navigate("/questions/4");
      }}
    >
      <div className="stepper-stack">
        {OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`option-card ${selected === option.id ? "option-card--selected" : ""}`}
            onClick={() => setSelected(option.id)}
          >
            <p className="option-card__title">{option.title}</p>
            <p className="option-card__desc">{option.desc}</p>
          </button>
        ))}
      </div>
    </QuestionLayout>
  );
}
