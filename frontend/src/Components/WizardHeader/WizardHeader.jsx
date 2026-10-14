import { useTranslation } from "react-i18next";
import BrandMark from "../BrandMark/BrandMark";
import LanguageToggle from "../LanguageToggle/LanguageToggle";
import "./WizardHeader.css";

export default function WizardHeader({ progress, onBack, onNext }) {
  const { t } = useTranslation();

  return (
    <header className="wizard-header">
      {/* DOM order is reversed from the visual left-to-right order so that
          RTL flex (first child -> visual right) reproduces the design:
          brand mark, brand text, mini-back, progress, mini-next, EN. */}
      <BrandMark size="sm" />

      <div className="wizard-header__brand">
        <p className="wizard-header__title">{t("brand.title")}</p>
        <p className="wizard-header__subtitle">{t("brand.subtitle")}</p>
      </div>

      {onBack && (
        <button type="button" className="wizard-header__mini-nav" onClick={onBack}>
          {t("wizard.back")}
        </button>
      )}

      <div className="wizard-header__progress">
        <div className="wizard-header__track">
          <div className="wizard-header__fill" style={{ width: `${progress * 100}%` }} />
        </div>
      </div>

      {onNext && (
        <button type="button" className="wizard-header__mini-nav" onClick={onNext}>
          {t("wizard.next")}
        </button>
      )}

      <LanguageToggle className="wizard-header__lang" />
    </header>
  );
}
