import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import QuestionLayout from "../../Components/QuestionLayout/QuestionLayout";
import Stepper from "../../Components/Stepper/Stepper";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";

export default function Question1() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const familyMembers = useFormStore((state) => state.familyMembers);
  const setFamilyMembers = useFormStore((state) => state.setFamilyMembers);
  const { adults, children } = familyMembers;

  return (
    <QuestionLayout
      stepIndex={1}
      stepLabel={t("q1.step")}
      title={t("q1.title")}
      subtitle={t("q1.subtitle")}
      onBack={() => navigate(-1)}
      onNext={() => {
        useFormStore.getState().saveBriefToBackend().catch(() => {});
        navigate("/questions/2");
      }}
    >
      <div className="stepper-stack">
        <Stepper
          label={t("q1.adults")}
          value={adults}
          onChange={(value) => setFamilyMembers({ adults: value, children })}
          min={1}
        />
        <Stepper
          label={t("q1.children")}
          value={children}
          onChange={(value) => setFamilyMembers({ adults, children: value })}
          min={0}
        />
      </div>
    </QuestionLayout>
  );
}
