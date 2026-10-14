import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import usePageTitle from "../../hooks/usePageTitle";
import LanguageToggle from "../../Components/LanguageToggle/LanguageToggle";
import "./Landing.css";

const arabicNumber = new Intl.NumberFormat("ar-EG");

// Counts up from 0 to `target` once it scrolls into view. Falls back to the
// final value immediately when reduced motion is preferred or IO is missing.
function prefersStaticCount() {
  if (typeof window === "undefined") return true;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reduce || typeof IntersectionObserver === "undefined";
}

function Counter({ target, className }) {
  const ref = useRef(null);
  const [value, setValue] = useState(() => (prefersStaticCount() ? target : 0));

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersStaticCount()) return undefined;

    let frame;
    let done = false;
    const runCount = () => {
      if (done) return;
      done = true;
      const duration = 1400;
      const start = performance.now();
      const tick = (now) => {
        const t = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - t, 3);
        setValue(Math.round(eased * target));
        if (t < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    };

    // Don't start counting until the parent .landing-reveal gains .is-visible
    const parent = el.closest(".landing-reveal");
    if (!parent) return undefined;

    if (parent.classList.contains("is-visible")) {
      runCount();
      return () => { if (frame) cancelAnimationFrame(frame); };
    }

    const observer = new MutationObserver(() => {
      if (parent.classList.contains("is-visible")) {
        observer.disconnect();
        runCount();
      }
    });
    observer.observe(parent, { attributes: true, attributeFilter: ["class"] });

    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [target]);

  return (
    <b ref={ref} className={className}>
      {arabicNumber.format(value)}
    </b>
  );
}

export default function Landing() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const numLocale = i18n.language === "ar" ? "ar-SA" : "en";
  const numFmt = (n) => new Intl.NumberFormat(numLocale).format(n);

  const steps = [
    {
      number: numFmt(1),
      title: t("landing.step1_title"),
      text: t("landing.step1_text"),
    },
    {
      number: numFmt(2),
      title: t("landing.step2_title"),
      text: t("landing.step2_text"),
    },
    {
      number: numFmt(3),
      title: t("landing.step3_title"),
      text: t("landing.step3_text"),
    },
  ];

  const features = [
    [t("landing.feature1_title"), t("landing.feature1_text")],
    [t("landing.feature2_title"), t("landing.feature2_text")],
    [t("landing.feature3_title"), t("landing.feature3_text")],
  ];
  const uploadRef = useRef(null);
  const pageRef = useRef(null);
  const heroImageRef = useRef(null);
  const [fileName, setFileName] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  const chooseFile = () => uploadRef.current?.click();

  function handleReview() {
    if (!selectedFile) return;
    navigate("/upload", { state: { file: selectedFile } });
  }

  // Scroll-reveal + hero parallax. Everything is opt-in via the "landing-js"
  // class added here, so if JS never runs (or reduced motion is preferred)
  // nothing is hidden or transformed — the page renders fully static.
  useEffect(() => {
    const page = pageRef.current;
    if (!page) return undefined;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return undefined;

    page.classList.add("landing-js");

    let observer;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add("is-visible");
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
      );
      page.querySelectorAll(".landing-reveal").forEach((el) => observer.observe(el));
    }

    // Failsafe: if the observer never reveals anything (e.g. IO throttled or
    // unsupported), force everything visible so content is never stuck hidden.
    const revealFailsafe = setTimeout(() => {
      if (!page.querySelector(".landing-reveal.is-visible")) {
        page.querySelectorAll(".landing-reveal").forEach((el) => el.classList.add("is-visible"));
      }
    }, 2200);

    let rafId = null;
    const onScroll = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        const img = heroImageRef.current;
        if (img) img.style.transform = `scale(1.05) translateY(${window.scrollY * 0.18}px)`;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      if (observer) observer.disconnect();
      clearTimeout(revealFailsafe);
      window.removeEventListener("scroll", onScroll);
      if (rafId) cancelAnimationFrame(rafId);
      page.classList.remove("landing-js");
    };
  }, []);

  return (
    <main className="landing-page" ref={pageRef}>
      <section className="landing-hero" id="home">
        <div className="landing-hero-image" aria-hidden="true" ref={heroImageRef} />
        <div className="landing-hero-shade" aria-hidden="true" />
        <div className="landing-hero-glow" aria-hidden="true" />

        <header className="landing-site-header">
          <a className="landing-brand" href="#home" aria-label="عَمِّر أرضك - الرئيسية">
            <span className="landing-brand-mark" aria-hidden="true">ع</span>
            <span>{t("brand.title")}</span>
          </a>

          <button
            className="landing-menu-button"
            type="button"
            aria-label="فتح القائمة"
            aria-expanded={isMenuOpen}
            onClick={() => setIsMenuOpen((value) => !value)}
          >
            <span />
            <span />
          </button>

          <nav
            className={isMenuOpen ? "landing-nav landing-nav-open" : "landing-nav"}
            aria-label="التنقل الرئيسي"
          >
            <a href="#how" onClick={() => setIsMenuOpen(false)}>{t("landing.nav_how")}</a>
            <a href="#features" onClick={() => setIsMenuOpen(false)}>{t("landing.nav_features")}</a>
            <a href="#results" onClick={() => setIsMenuOpen(false)}>{t("landing.nav_results")}</a>
            <LanguageToggle className="landing-nav-lang" />
            <Link className="landing-nav-cta" to="/upload" onClick={() => setIsMenuOpen(false)}>
              {t("landing.nav_cta")}
            </Link>
          </nav>
        </header>

        <div className="landing-hero-content">
          <div className="landing-eyebrow"><span /> {t("landing.eyebrow")}</div>
          <h1>{t("landing.hero_title")}</h1>
          <p>{t("landing.hero_desc")}</p>
          <div className="landing-hero-actions">
            <Link className="landing-primary-button" to="/upload">
              {t("landing.start_cta")}
            </Link>
            <a className="landing-text-button" href="#how">{t("landing.see_how")}</a>
          </div>
          <div className="landing-trust-line">
            <span aria-hidden="true">✓</span> {t("landing.trust_free")}
            <i />
            <span aria-hidden="true">◇</span> {t("landing.trust_private")}
          </div>
        </div>

        <a className="landing-scroll-cue" href="#how" aria-label="انتقل إلى القسم التالي">
          <span>{t("landing.scroll_cue")}</span>
          <b aria-hidden="true" style={{ display: "inline-flex" }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </b>
        </a>
      </section>

      <section className="landing-how landing-section" id="how">
        <div className="landing-section-intro landing-reveal">
          <span className="landing-kicker">{t("landing.how_kicker")}</span>
          <h2>{t("landing.how_title")}</h2>
          <p>{t("landing.how_desc")}</p>
        </div>

        <div className="landing-steps-grid">
          {steps.map((step, index) => (
            <article className="landing-step-card landing-reveal" key={`step-${index}`}>
              <div className="landing-step-top">
                <span className="landing-step-number">{step.number}</span>
                <span className="landing-step-icon" aria-hidden="true">
                  {index === 0 ? (
                    <svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                      <polyline points="14 2 14 8 20 8"/>
                      <line x1="12" y1="12" x2="12" y2="18"/>
                      <polyline points="9 15 12 12 15 15"/>
                    </svg>
                  ) : index === 1 ? (
                    <svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                      <polyline points="9 22 9 12 15 12 15 22"/>
                    </svg>
                  ) : (
                    <svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="3" width="18" height="18" rx="2"/>
                      <line x1="3" y1="9" x2="21" y2="9"/>
                      <line x1="3" y1="15" x2="21" y2="15"/>
                      <line x1="9" y1="3" x2="9" y2="21"/>
                      <line x1="15" y1="3" x2="15" y2="21"/>
                    </svg>
                  )}
                </span>
              </div>
              <h3>{step.title}</h3>
              <p>{step.text}</p>

            </article>
          ))}
        </div>
      </section>

      <section className="landing-start-section landing-section" id="start">
        <div className="landing-start-copy">
          <span className="landing-kicker landing-kicker--light">{t("landing.start_kicker")}</span>
          <h2>{t("landing.start_title")}</h2>
          <p>{t("landing.start_desc")}</p>
          <ul>
            <li><span>✓</span> {t("landing.start_bullet1")}</li>
            <li><span>✓</span> {t("landing.start_bullet2")}</li>
            <li><span>✓</span> {t("landing.start_bullet3")}</li>
          </ul>
        </div>

        <div className="landing-upload-card">
          <div className="landing-upload-header">
            <div>
              <small>{t("landing.upload_header_small")}</small>
              <h3>{fileName ? t("landing.upload_header_ready") : t("landing.upload_header_upload")}</h3>
            </div>
            <span className="landing-secure-badge">{t("landing.upload_badge")}</span>
          </div>

          <button
            className={fileName ? "landing-drop-zone landing-drop-zone--chosen" : "landing-drop-zone"}
            type="button"
            onClick={chooseFile}
          >
            <span className="landing-upload-icon" aria-hidden="true">{fileName ? "✓" : "↑"}</span>
            <strong>{fileName ? t("landing.upload_drop_selected") : t("landing.upload_drop_empty")}</strong>
            <span>{fileName ? t("landing.upload_change") : t("landing.upload_formats")}</span>
          </button>
          <input
            ref={uploadRef}
            className="landing-visually-hidden"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                setFileName(file.name);
                setSelectedFile(file);
              }
            }}
          />

          <button className="landing-upload-action" type="button" onClick={fileName ? handleReview : chooseFile}>
            {fileName ? t("landing.upload_action_review") : t("landing.upload_action_choose")}
          </button>
          <button className="landing-manual-action" type="button">{t("landing.upload_manual")}</button>
          <p className="landing-privacy-note"><span aria-hidden="true">◇</span> {t("landing.upload_privacy")}</p>
        </div>
      </section>

      <section className="landing-features landing-section" id="features">
        <div className="landing-section-intro landing-split-intro landing-reveal">
          <div>
            <span className="landing-kicker">{t("landing.features_kicker")}</span>
            <h2>{t("landing.features_title")}</h2>
          </div>
          <p>{t("landing.features_desc")}</p>
        </div>

        <div className="landing-feature-grid">
          {features.map(([title, text], index) => (
            <article className="landing-feature-card landing-reveal" key={`feature-${index}`}>
              <div className="landing-feature-top">
                <span className="landing-feature-index">{numFmt(index + 1).padStart(2, i18n.language === "ar" ? "٠" : "0")}</span>
                <div className="landing-feature-glyph" aria-hidden="true">
                {index === 0 ? (
                  <svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                    <circle cx="10" cy="14" r="3"/>
                    <line x1="12.5" y1="16.5" x2="15" y2="19"/>
                  </svg>
                ) : index === 1 ? (
                  <svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                    <circle cx="9" cy="7" r="4"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                  </svg>
                ) : (
                  <svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/>
                    <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88"/>
                  </svg>
                )}
              </div>
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-results landing-section" id="results">
        <div className="landing-result-visual landing-reveal">
          <img
            className="landing-result-image"
            src="/floor-plan-sample.jpeg"
            alt="مخطط أولي ثنائي الأبعاد لأرض بمساحة 2,892.3 م²"
          />
          <div className="landing-result-tag"><Counter target={2892} /><span>{t("landing.result_area")}</span></div>
        </div>

        <div className="landing-result-copy landing-reveal">
          <span className="landing-kicker landing-kicker--light">{t("landing.result_kicker")}</span>
          <h2>{t("landing.result_title")}</h2>
          <p>{t("landing.result_desc")}</p>
          <div className="landing-result-stats">
            <div><strong>{t("landing.result_stat_2d")}</strong><span>{t("landing.result_stat_2d_label")}</span></div>
            <div><strong>{t("landing.result_stat_3d")}</strong><span>{t("landing.result_stat_3d_label")}</span></div>
            <div><strong>{t("landing.result_stat_pdf")}</strong><span>{t("landing.result_stat_pdf_label")}</span></div>
          </div>
          <Link className="landing-outline-button" to="/upload">
            {t("landing.result_cta")}
          </Link>
        </div>
      </section>

      <section className="landing-final-cta landing-section landing-reveal">
        <span className="landing-kicker">{t("landing.final_kicker")}</span>
        <h2>{t("landing.final_title")}</h2>
        <Link className="landing-primary-button" to="/upload">
          {t("landing.final_cta")}
        </Link>
      </section>

      <footer className="landing-footer">
        <a className="landing-brand landing-footer-brand" href="#home">
          <span className="landing-brand-mark" aria-hidden="true">ع</span>
          <span>{t("brand.title")}</span>
        </a>
        <p>{t("landing.footer_desc")}</p>
        <div className="landing-footer-links">
          <a href="#how">{t("landing.footer_how")}</a>
          <a href="#features">{t("landing.footer_features")}</a>
          <a href="#start">{t("landing.footer_start")}</a>
        </div>
        <small>{t("landing.footer_rights")}</small>
      </footer>
    </main>
  );
}
