import { lazy, Suspense, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Navbar from "../../Components/Navbar/Navbar";
import Button from "../../Components/Button/Button";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";
import "./ExtractionFailed.css";

const LocationMapPicker = lazy(() => import("../../Components/LocationMapPicker/LocationMapPicker"));

export default function ExtractionFailed() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const FIELDS = [
    { key: "width", label: t("manual.width"), placeholder: t("manual.placeholder_width"), required: true },
    { key: "height", label: t("manual.height"), placeholder: t("manual.placeholder_height"), required: true },
    { key: "street", label: t("manual.street"), placeholder: t("manual.placeholder_street"), required: true },
  ];
  // The error banner only shows when we actually failed to read the deed
  // (backend/OCR error). Choosing "enter manually" from Upload shows just the form.
  const extractionFailed = Boolean(location.state?.extractionFailed);
  const errorMessage = location.state?.errorMessage || t("extraction_failed.title");
  const setLandDimensions = useFormStore((state) => state.setLandDimensions);
  const setLandCoordinates = useFormStore((state) => state.setLandCoordinates);
  const setLandRotation = useFormStore((state) => state.setLandRotation);
  const [values, setValues] = useState({ width: "", height: "", street: "" });
  const [coords, setCoords] = useState({ lat: "", lng: "" });
  const [coordsTouched, setCoordsTouched] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [pickedFromMap, setPickedFromMap] = useState(false);
  const [rotation, setRotation] = useState(0);

  const isComplete = FIELDS.every((field) => values[field.key].trim() !== "");
  const coordsComplete =
    coords.lat.trim() !== "" &&
    coords.lng.trim() !== "" &&
    !isNaN(Number(coords.lat)) &&
    !isNaN(Number(coords.lng));

  function handleChange(key, value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function handleContinue() {
    if (!isComplete || !coordsComplete) {
      setCoordsTouched(true);
      return;
    }
    setLandDimensions({ width: values.width, height: values.height });
    setLandCoordinates({ lat: Number(coords.lat), lng: Number(coords.lng) });
    setLandRotation(rotation);
    // Manual entry persists exactly like the extraction path.
    try {
      await useFormStore.getState().savePlotToBackend({
        source: "manual",
        street_width_m: values.street ? Number(values.street) : null,
      });
    } catch (err) {
      console.warn("plot save failed; continuing (will retry at generation):", err);
    }
    navigate("/questions/1", { state: { landData: values } });
  }

  return (
    <div className="page">
      <Navbar />
      <main className="extraction-failed">
        {extractionFailed && (
          <>
            <div className="error-banner">
              <p className="error-banner__mark">!</p>
              <div className="error-banner__text">
                <p className="error-banner__title">{t("extraction_failed.title")}</p>
                <p className="error-banner__subtitle">{errorMessage}</p>
              </div>
            </div>

            <Button variant="secondary" onClick={() => navigate("/upload")}>
              {t("extraction_failed.retry")}
            </Button>

            <p className="extraction-failed__divider">{t("extraction_failed.divider")}</p>
          </>
        )}

        <div className="manual-form">
          <p className="manual-form__title">{t("manual.title")}</p>
          <p className="manual-form__subtitle">{t("manual.subtitle")}</p>

          {FIELDS.map((field) => (
            <label className="manual-form__field" key={field.key}>
              <span className="manual-form__label">{field.label}</span>
              <input
                type="number"
                className="manual-form__input"
                placeholder={field.placeholder}
                value={values[field.key]}
                onChange={(event) => handleChange(field.key, event.target.value)}
              />
            </label>
          ))}

          <div className="manual-form__divider" />

          <p className="manual-form__hint">
            {t("manual.coords_hint")}
          </p>

          <button type="button" className="manual-form__map-btn" onClick={() => setMapOpen(true)}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
              <path
                d="M12 21s7-6.5 7-11.5A7 7 0 0 0 5 9.5C5 14.5 12 21 12 21Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <circle cx="12" cy="9.5" r="2.4" stroke="currentColor" strokeWidth="1.6" />
            </svg>
            {t("map.pick_button")}
          </button>
          {pickedFromMap && <p className="manual-form__picked-hint">{t("map.picked_hint")}</p>}

          <label className="manual-form__field">
            <span className="manual-form__label">{t("manual.coords_lat")}</span>
            <input
              type="number"
              step="any"
              inputMode="decimal"
              className={`manual-form__input${
                coordsTouched && coords.lat.trim() === "" ? " manual-form__input--error" : ""
              }`}
              placeholder={t("manual.coords_placeholder_lat")}
              value={coords.lat}
              onChange={(e) => {
                setCoords((c) => ({ ...c, lat: e.target.value }));
                setPickedFromMap(false);
              }}
            />
          </label>
          <label className="manual-form__field">
            <span className="manual-form__label">{t("manual.coords_lng")}</span>
            <input
              type="number"
              step="any"
              inputMode="decimal"
              className={`manual-form__input${
                coordsTouched && coords.lng.trim() === "" ? " manual-form__input--error" : ""
              }`}
              placeholder={t("manual.coords_placeholder_lng")}
              value={coords.lng}
              onChange={(e) => {
                setCoords((c) => ({ ...c, lng: e.target.value }));
                setPickedFromMap(false);
              }}
            />
          </label>

          {coordsTouched && !coordsComplete && (
            <p className="manual-form__error">{t("manual.coords_error")}</p>
          )}

          <Button fullWidth disabled={!isComplete || !coordsComplete} onClick={handleContinue}>
            {t("manual.btn")}
          </Button>
        </div>
      </main>

      {mapOpen && (
        <Suspense fallback={null}>
          <LocationMapPicker
            initialLat={coords.lat ? Number(coords.lat) : null}
            initialLng={coords.lng ? Number(coords.lng) : null}
            landWidth={values.width}
            landHeight={values.height}
            initialRotationDeg={rotation}
            onConfirm={({ lat, lng, widthM, heightM, rotationDeg }) => {
              setCoords({ lat: String(lat), lng: String(lng) });
              setValues((v) => ({
                ...v,
                width: String(Math.round(widthM * 10) / 10),
                height: String(Math.round(heightM * 10) / 10),
              }));
              setRotation(rotationDeg);
              setPickedFromMap(true);
              setMapOpen(false);
            }}
            onClose={() => setMapOpen(false)}
          />
        </Suspense>
      )}
    </div>
  );
}
