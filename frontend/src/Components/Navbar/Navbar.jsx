import { useTranslation } from "react-i18next";
import BrandMark from "../BrandMark/BrandMark";
import LanguageToggle from "../LanguageToggle/LanguageToggle";
import "./Navbar.css";

export default function Navbar() {
  const { t } = useTranslation();

  return (
    <header className="navbar">
      <div className="navbar__brand">
        <BrandMark size="sm" />
        <p className="navbar__title">{t("brand.title")}</p>
      </div>
      <LanguageToggle className="navbar__lang" />
    </header>
  );
}
