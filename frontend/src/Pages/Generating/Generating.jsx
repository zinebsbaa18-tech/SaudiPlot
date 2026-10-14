import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Navbar from "../../Components/Navbar/Navbar";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";
import * as Api from "../../Api/Api";
import "./Generating.css";

const SUCCESS_DISPLAY_TIME = 1800;
const POLL_INTERVAL_MS = 1500;

// Real backend run statuses mapped onto the four frozen progress rows.
const STEP_FOR_STATUS = {
  preparing_inputs: 0,
  extracting_deed: 0,
  resolving_character: 1,
  validating_requirements: 1,
  generating_candidates: 2,
  evaluating_candidates: 2,
  preparing_outputs: 3,
  generating_presentation_render: 3,
};

const TERMINAL_OK = ["completed", "completed_with_assumptions"];
const TERMINAL_FAIL = ["unsupported_requirements", "failed"];

// Module-level so React StrictMode's double-mounted effect (and a re-entered
// /generating during the same run) reuses one in-flight run instead of
// starting a second one or cancelling the first closure's polling.
let activeRunPromise = null;

async function ensureRunStarted() {
  if (!activeRunPromise) {
    activeRunPromise = (async () => {
      const store = useFormStore.getState();
      const project = await store.ensureProject();
      await store.saveBriefToBackend();
      await store.saveRoomProgramToBackend();
      try {
        await Api.resolveCharacter(project.id);
      } catch (err) {
        // Advisory only -- generation itself reports the applied character.
        console.warn("character resolution unavailable:", err);
      }
      const run = await Api.startDesignRun(project.id);
      Api.rememberRunId(run.id);
      return run.id;
    })().catch((err) => {
      activeRunPromise = null;
      throw err;
    });
  }
  return activeRunPromise;
}

export default function Generating() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [activeIndex, setActiveIndex] = useState(0);
  const [phase, setPhase] = useState("progress");

  const STEPS = [
    t("generating.step1"),
    t("generating.step2"),
    t("generating.step3"),
    t("generating.step4"),
  ];
  const stepCount = STEPS.length;

  // Drive the frozen progress UI from the real design run: persist all
  // answers, start the run, and poll actual backend statuses. No timers
  // simulate progress -- every advance reflects a reported backend state.
  useEffect(() => {
    let cancelled = false;
    let pollTimer = null;

    function fail(message) {
      if (cancelled) return;
      activeRunPromise = null;
      navigate("/manual-entry", {
        state: { extractionFailed: true, errorMessage: message },
      });
    }

    async function poll(runId) {
      if (cancelled) return;
      try {
        const run = await Api.getDesignRun(runId);
        if (TERMINAL_OK.includes(run.status)) {
          activeRunPromise = null;
          if (!cancelled) {
            setActiveIndex(stepCount);
            setTimeout(() => {
              if (!cancelled) setPhase("success");
            }, 300);
          }
          return;
        }
        if (TERMINAL_FAIL.includes(run.status)) {
          const detail =
            run.status === "unsupported_requirements"
              ? "المتطلبات الحالية خارج نطاق المحرك؛ راجع بيانات الأرض المدخلة."
              : "تعذر إكمال التصميم بسبب خطأ داخلي. حاول مرة أخرى.";
          fail(detail);
          return;
        }
        const step = STEP_FOR_STATUS[run.status];
        if (step !== undefined && !cancelled) {
          setActiveIndex((previous) => Math.max(previous, step));
        }
      } catch (err) {
        console.warn("run poll failed, retrying:", err);
      }
      if (!cancelled) {
        pollTimer = setTimeout(() => poll(runId), POLL_INTERVAL_MS);
      }
    }

    ensureRunStarted()
      .then((runId) => poll(runId))
      .catch((err) => fail(err.message || t("extraction_failed.title")));

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (phase !== "success") return undefined;
    const timeout = setTimeout(() => navigate("/result-3d"), SUCCESS_DISPLAY_TIME);
    return () => clearTimeout(timeout);
  }, [phase, navigate]);

  if (phase === "success") {
    return (
      <div className="page">
        <Navbar />
        <main className="generating">
          <div className="success-check">
            <svg viewBox="0 0 80 80" width="80" height="80" aria-hidden="true">
              <circle className="success-check__circle" cx="40" cy="40" r="36" fill="none" />
              <path className="success-check__mark" fill="none" d="M24 41 L35 52 L57 28" />
            </svg>
          </div>
          <h1 className="generating__title generating__title--success">{t("generating.success_title")}</h1>
          <p className="generating__hint">{t("generating.success_hint")}</p>
        </main>
      </div>
    );
  }

  return (
    <div className="page">
      <Navbar />
      <main className="generating">
        <div className="generating__spinner" aria-hidden="true" />
        <h1 className="generating__title">{t("generating.title")}</h1>

        <div className="generating__card">
          {STEPS.map((step, index) => (
            <div
              className={`generating__row ${
                index === activeIndex
                  ? "generating__row--active"
                  : index > activeIndex
                    ? "generating__row--pending"
                    : ""
              }`}
              key={step}
            >
              <span
                className={`generating__mark ${
                  index < activeIndex
                    ? "generating__mark--done"
                    : index === activeIndex
                      ? "generating__mark--active"
                      : "generating__mark--pending"
                }`}
              >
                {index < activeIndex ? "✓" : ""}
              </span>
              <p className="generating__text">{step}</p>
            </div>
          ))}
        </div>

        <p className="generating__hint">{t("generating.hint")}</p>
      </main>
    </div>
  );
}
