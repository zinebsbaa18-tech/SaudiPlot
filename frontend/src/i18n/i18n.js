import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import ar from "./locales/ar.json";
import en from "./locales/en.json";

function syncDir(lng) {
  document.documentElement.dir = lng === "ar" ? "rtl" : "ltr";
  document.documentElement.lang = lng;
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { ar: { translation: ar }, en: { translation: en } },
    fallbackLng: "ar",
    detection: {
      order: ["localStorage"],
      caches: ["localStorage"],
    },
    interpolation: { escapeValue: false },
  });

syncDir(i18n.language);
i18n.on("languageChanged", syncDir);

export default i18n;
