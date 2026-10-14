import { useTranslation } from "react-i18next";
import "./LanguageToggle.css";

export default function LanguageToggle({ className = "" }) {
  const { i18n } = useTranslation();
  const isAr = i18n.language === "ar";

  return (
    <button
      type="button"
      className={`lang-toggle ${className}`}
      onClick={() => i18n.changeLanguage(isAr ? "en" : "ar")}
      aria-label={isAr ? "Switch to English" : "التبديل إلى العربية"}
    >
      <span className={`lang-toggle__option ${isAr ? "lang-toggle__option--active" : ""}`}>AR</span>
      <span className="lang-toggle__divider" />
      <span className={`lang-toggle__option ${!isAr ? "lang-toggle__option--active" : ""}`}>EN</span>
    </button>
  );
}
