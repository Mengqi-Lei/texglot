import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import en from "./en.json";
export type Locale = "zh" | "en";
const key = "texglot-ui-locale";
export function savedLocale(): Locale {
  try {
    return localStorage.getItem(key) === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}
let currentLocale = savedLocale();
export const getLocale = () => currentLocale;
type Translate = (
  text: string,
  values?: Record<string, string | number>,
) => string;
export function translate(
  locale: Locale,
  text: string,
  values: Record<string, string | number> = {},
): string {
  let value =
    locale === "en" ? ((en as Record<string, string>)[text] ?? text) : text;
  if (locale === "en" && values.count === 1)
    value = value.replace(/\b(pages|paragraphs|tasks)\b/g, (unit) =>
      unit.slice(0, -1),
    );
  return value.replace(/\{(\w+)\}/g, (match, name) =>
    String(values[name] ?? match),
  );
}
const Context = createContext<{
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: Translate;
}>({ locale: "zh", setLocale: () => {}, t: (s) => s });
export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, update] = useState<Locale>(savedLocale);
  const setLocale = (value: Locale) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* Session-only preference if storage is unavailable. */
    }
    currentLocale = value;
    update(value);
  };
  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = `TeXGlot · ${translate(locale, "本地学术翻译")}`;
  }, [locale]);
  return (
    <Context.Provider
      value={{ locale, setLocale, t: (s, v) => translate(locale, s, v) }}
    >
      {children}
    </Context.Provider>
  );
}
export const useI18n = () => useContext(Context);
