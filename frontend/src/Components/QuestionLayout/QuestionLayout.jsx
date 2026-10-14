import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import Button from "../Button/Button";
import WizardHeader from "../WizardHeader/WizardHeader";
import { WIZARD_STEPS } from "./wizardSteps";
import { useSlideDirection } from "./SlideDirectionContext";
import { slideVariants, slideTransition } from "./slideVariants";
import "./QuestionLayout.css";

export default function QuestionLayout({
  stepIndex,
  stepLabel,
  title,
  subtitle,
  children,
  onBack,
  onNext,
  nextDisabled = false,
  nextLabel: nextLabelProp,
  backLabel: backLabelProp,
  singleAction = false,
}) {
  const { t } = useTranslation();
  const nextLabel = nextLabelProp ?? t("question.next");
  const backLabel = backLabelProp ?? t("question.back");
  const progress = stepIndex / WIZARD_STEPS.length;
  const StepIcon = WIZARD_STEPS[stepIndex - 1]?.Icon;
  const direction = useSlideDirection();

  return (
    <motion.div
      className="page page--carousel"
      custom={direction}
      variants={slideVariants}
      initial="enter"
      animate="center"
      exit="exit"
      transition={slideTransition}
    >
      <WizardHeader progress={progress} onBack={onBack} onNext={singleAction ? undefined : onNext} />
      <main className="question-wizard">
        {/* Sidebar is first in DOM so RTL flex places it on the visual RIGHT,
            with the question card on the LEFT — matching the design. */}
        <aside className="wizard-sidebar">
          <p className="wizard-sidebar__title">{t("wizard.sidebar.title")}</p>
          <p className="wizard-sidebar__subtitle">{t("wizard.sidebar.subtitle")}</p>

          <div className="wizard-sidebar__list">
            {WIZARD_STEPS.map(({ path, labelKey, Icon }, idx) => {
              const num = idx + 1;
              const status = num < stepIndex ? "done" : num === stepIndex ? "active" : "pending";
              return (
                <div className={`wizard-sidebar__item wizard-sidebar__item--${status}`} key={path}>
                  {/* DOM order reversed (label, icon, badge) so RTL flex places
                      the label at the visual right and the badge at the left. */}
                  <span className="wizard-sidebar__label">{t(labelKey)}</span>
                  <span className="wizard-sidebar__icon">
                    <Icon />
                  </span>
                  <span className="wizard-sidebar__badge">{status === "done" ? "✓" : num}</span>
                </div>
              );
            })}
          </div>
        </aside>

        <section className="question-wizard__card">
          <div className="question__progress">
            {StepIcon && (
              <span className="question__icon">
                <StepIcon />
              </span>
            )}
            <p className="question__step">{stepLabel}</p>
          </div>

          <h1 className="question__title">{title}</h1>
          {subtitle && <p className="question__subtitle">{subtitle}</p>}

          <div className="question__content">{children}</div>

          {singleAction ? (
            <Button fullWidth onClick={onNext} disabled={nextDisabled}>
              {nextLabel}
            </Button>
          ) : (
            <div className="question__nav">
              {/* Next renders first so RTL flex (justify-content: space-between)
                  places it on the visual right, Back on the visual left — matching the design. */}
              <Button onClick={onNext} disabled={nextDisabled}>
                {nextLabel}
              </Button>
              <Button variant="secondary" onClick={onBack}>
                {backLabel}
              </Button>
            </div>
          )}
        </section>
      </main>
    </motion.div>
  );
}
