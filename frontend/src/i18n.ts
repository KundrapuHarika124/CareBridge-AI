import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import type { Lang } from "./api";
import en from "./locales/en.json";
import te from "./locales/te.json";

// Language display names in their native scripts
export const LANGUAGE_NAMES: Record<Lang, { en: string; native: string }> = {
  en: { en: "English", native: "English" },
  hi: { en: "Hindi", native: "हिन्दी" },
  te: { en: "Telugu", native: "తెలుగు" },
  ta: { en: "Tamil", native: "தமிழ்" },
  kn: { en: "Kannada", native: "ಕನ್ನಡ" },
  ml: { en: "Malayalam", native: "മലയാളം" },
  bn: { en: "Bengali", native: "বাংলা" },
  mr: { en: "Marathi", native: "मराठी" },
  gu: { en: "Gujarati", native: "ગુજરાતી" },
  pa: { en: "Punjabi", native: "ਪੰਜਾਬੀ" },
  ur: { en: "Urdu", native: "اردو" },
};

const STORAGE_KEY = "cb_lang";

function storedLanguage(): Lang {
  try {
    const lang = localStorage.getItem(STORAGE_KEY);
    if (lang && lang in LANGUAGE_NAMES) return lang as Lang;
    return "en";
  } catch {
    return "en";
  }
}

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, te: { translation: te } },
  lng: storedLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false }, // React already escapes
});

export function setLanguage(lang: Lang): void {
  i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = (lang === "ur") ? "rtl" : "ltr";
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}

export function currentLanguage(): Lang {
  const lang = i18n.language;
  return (lang as Lang) in LANGUAGE_NAMES ? (lang as Lang) : "en";
}

export default i18n;
