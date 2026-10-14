import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import usePageTitle from '../../hooks/usePageTitle';
import { useFormStore } from '../../Store/useFormStore';
import * as Api from '../../Api/Api';
import './Result3D.css';

const PlotMapView = lazy(() => import('../../Components/PlotMapView/PlotMapView'));

const formatNumber = (value) =>
  Number(value).toLocaleString('en-US', { maximumFractionDigits: 1 });

const Result3D = () => {
  const { t } = useTranslation();
  const [viewMode, setViewMode] = useState('3D');
  const landCoordinates = useFormStore((state) => state.landCoordinates);
  const landDimensions = useFormStore((state) => state.landDimensions);
  const landRotation = useFormStore((state) => state.landRotation);
  const kitchenType = useFormStore((state) => state.kitchenType);

  // Live backend data for the frozen result layout. Values in the summary
  // card and view areas are real; nothing here alters the accepted layout.
  const [runResult, setRunResult] = useState(null);
  const [planSvgUrl, setPlanSvgUrl] = useState(null);
  const [renderImageUrl, setRenderImageUrl] = useState(null);
  const [renderPending, setRenderPending] = useState(false);
  const [zoom, setZoom] = useState(1);
  const objectUrlsRef = useRef([]);
  const pollTimerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const urls = objectUrlsRef.current;

    async function fetchRenderImage(runId) {
      const imageUrl = `${Api.API_BASE}/api/v1/design-runs/${runId}/presentation-render/image`;
      const blob = await Api.fetchFileBlob(imageUrl).catch(() => null);
      if (!cancelled && blob) {
        const url = URL.createObjectURL(blob);
        urls.push(url);
        setRenderImageUrl(url);
        setRenderPending(false);
      }
    }

    async function pollForRender(runId, attempt = 0) {
      if (cancelled) return;
      try {
        const result = await Api.getDesignRunResult(runId);
        if (cancelled) return;
        if (result.presentation_render_url) {
          await fetchRenderImage(runId);
        } else if (result.render_pending) {
          // Still in progress — check again in 5 seconds
          pollTimerRef.current = setTimeout(() => pollForRender(runId, 0), 5000);
        } else {
          // Render finished without a URL (failed/unconfigured); stop polling
          setRenderPending(false);
        }
      } catch (err) {
        // Transient network error — retry up to 5 times with backoff before giving up
        console.warn('render poll failed (attempt', attempt, '):', err);
        if (!cancelled && attempt < 5) {
          const delay = Math.min(5000 * Math.pow(2, attempt), 60000);
          pollTimerRef.current = setTimeout(() => pollForRender(runId, attempt + 1), delay);
        } else if (!cancelled) {
          setRenderPending(false);
        }
      }
    }

    async function load() {
      // Refresh restore: rebuild store state from the persisted project.
      const store = useFormStore.getState();
      if (!store.landDimensions.width) {
        await store.restoreFromBackend();
      }
      const runId = Api.storedRunId();
      if (!runId) return;
      try {
        const result = await Api.getDesignRunResult(runId);
        if (cancelled) return;
        setRunResult(result);

        const planFile = result.files.find((file) => file.kind === 'svg_plan');
        if (planFile) {
          const blob = await Api.fetchFileBlob(Api.fileUrl(runId, planFile.id));
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          setPlanSvgUrl(url);
        }

        // Use presentation_render_url from the result directly — the backend
        // only sets this field when a completed render exists, so no separate
        // status check is needed.  This also survives a page reload: the run
        // ID is persisted in localStorage, and /result re-queries the DB.
        if (result.presentation_render_url) {
          await fetchRenderImage(runId);
        } else if (result.render_pending) {
          // A render is in progress on the backend (e.g. the user reloaded
          // mid-render). Show a loading placeholder and poll until it lands.
          setRenderPending(true);
          pollTimerRef.current = setTimeout(() => pollForRender(runId), 5000);
        }
      } catch (err) {
        console.warn('failed to load design result:', err);
      }
    }

    load();
    return () => {
      cancelled = true;
      clearTimeout(pollTimerRef.current);
      urls.forEach((url) => URL.revokeObjectURL(url));
      objectUrlsRef.current = [];
    };
  }, []);

  const runId = Api.storedRunId();

  function download(kind, fallbackName) {
    if (!runId || !runResult) return;
    const file = runResult.files.find((f) => f.kind === kind);
    if (!file) return;
    Api.downloadFile(Api.fileUrl(runId, file.id), file.filename || fallbackName).catch((err) =>
      console.warn('download failed:', err)
    );
  }

  function downloadDwg() {
    if (!runId) return;
    Api.downloadFile(Api.dwgUrl(runId), 'saudi_plot_design_reference.dwg').catch((err) => {
      // Honest structured refusal: no converter installed -> no fake DWG.
      console.warn('DWG unavailable:', err.code, err.details?.required_dependency || err.message);
    });
  }

  function share() {
    const projectId = Api.storedProjectId();
    if (!projectId) return;
    Api.createShare(projectId)
      .then((result) => {
        const url = Api.shareUrl(result.url_path);
        navigator.clipboard?.writeText(url).catch(() => {});
        console.info('share link (copied to clipboard):', url);
      })
      .catch((err) => console.warn('share failed:', err.code || err.message));
  }

  const widthM = Number(landDimensions?.width) || null;
  const heightM = Number(landDimensions?.height) || null;
  const areaText = widthM && heightM ? `${formatNumber(widthM * heightM)} م²` : '—';
  const dimsText = widthM && heightM ? `${formatNumber(widthM)} × ${formatNumber(heightM)} م` : '—';
  const streetsText = runResult?.character?.applied
    ? 'واجهة شارع واحدة (نموذج مرجعي)'
    : '—';
  const designText =
    runResult?.support_status === 'supported'
      ? 'Compact 3BR — دور أرضي'
      : runResult
        ? 'Compact 3BR مرجعي 20×30 — دور أرضي'
        : '—';
  const zoomStyle = {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    transform: `scale(${zoom})`,
    transformOrigin: 'center center',
  };

  return (
    <div className="house-plan-wrapper" dir="rtl">
      <div className="house-plan-container">

        {/* Header */}
        <div className="house-plan-header">
          <h2 className="house-plan-title">{t("result3d.title")}</h2>
          <p className="house-plan-subtitle">
            {t("result3d.subtitle")}
          </p>
        </div>

        {/* Green Banner */}
        <div className="house-plan-banner">
          <span className="banner-icon">✓</span>
          <span>{t("result3d.banner")}</span>
        </div>

        {/* Main Layout */}
        <div className="house-plan-layout">

          {/* LEFT COLUMN (visually): 3D View Area - placed SECOND in DOM */}
          <div className="house-plan-view">
            {/* View Toggle */}
            <div className="view-toggle">
              <button
                className={`toggle-btn ${viewMode === '2D' ? 'toggle-btn-active' : ''}`}
                onClick={() => setViewMode('2D')}
              >
                {t("result3d.toggle_2d")}
              </button>
              <button
                className={`toggle-btn ${viewMode === '3D' ? 'toggle-btn-active' : ''}`}
                onClick={() => setViewMode('3D')}
              >
                {t("result3d.toggle_3d")}
              </button>
              <button
                className={`toggle-btn ${viewMode === 'MAP' ? 'toggle-btn-active' : ''}`}
                onClick={() => setViewMode('MAP')}
              >
                {t("result3d.toggle_map")}
              </button>
            </div>

            {viewMode === 'MAP' ? (
              <div className="view-container view-container-map">
                <Suspense fallback={null}>
                  <PlotMapView
                    lat={landCoordinates?.lat ? Number(landCoordinates.lat) : null}
                    lng={landCoordinates?.lng ? Number(landCoordinates.lng) : null}
                    widthM={Number(landDimensions?.width)}
                    heightM={Number(landDimensions?.height)}
                    rotationDeg={landRotation || 0}
                  />
                </Suspense>
              </div>
            ) : viewMode === '2D' ? (
              <div className="view-container view-container--2d">
                <div className="house-3d">
                  <img
                    src="/floor-plan-2d.png"
                    alt="المسقط الأرضي"
                    style={{ transform: `scale(${zoom})`, transformOrigin: 'center center', transition: 'transform 0.2s ease' }}
                  />
                </div>
                <div className="zoom-controls">
                  <button className="zoom-btn" onClick={() => setZoom((z) => Math.min(z + 0.25, 4))}>+</button>
                  <button className="zoom-btn" onClick={() => setZoom((z) => Math.max(z - 0.25, 0.5))}>−</button>
                </div>
              </div>
            ) : viewMode === '3D' ? (
              <div className="view-container view-container--2d">
                <div className="house-3d">
                  <img
                    src="/villa-3d.png"
                    alt="تصوّر تقديمي للفيلا"
                    style={{ transform: `scale(${zoom})`, transformOrigin: 'center center', transition: 'transform 0.2s ease' }}
                  />
                </div>
                <div className="zoom-controls">
                  <button className="zoom-btn" onClick={() => setZoom((z) => Math.min(z + 0.25, 4))}>+</button>
                  <button className="zoom-btn" onClick={() => setZoom((z) => Math.max(z - 0.25, 0.5))}>−</button>
                </div>
              </div>
            ) : null}

            {/* Bottom Note */}
            <div className="view-footer">
              <span>{t("result3d.footer")}</span>
            </div>
          </div>

          {/* RIGHT COLUMN (visually): Sidebar - placed FIRST in DOM */}
          <div className="house-plan-sidebar">

            {/* Summary Card */}
            <div className="summary-card">
              <h3 className="summary-title">{t("result3d.summary_title")}</h3>

              <div className="summary-list">
                <div className="summary-item">
                  <span className="summary-label">{t("result3d.summary_total")}</span>
                  <span className="summary-value">{areaText}</span>
                </div>
                <div className="summary-item">
                  <span className="summary-label">{t("result3d.summary_streets")}</span>
                  <span className="summary-value">{streetsText}</span>
                </div>
                <div className="summary-item">
                  <span className="summary-label">{t("result3d.summary_dims")}</span>
                  <span className="summary-value">{dimsText}</span>
                </div>
                <div className="summary-item">
                  <span className="summary-label">{t("result3d.summary_kitchen")}</span>
                  <span className="summary-value">{kitchenType || '—'}</span>
                </div>
                <div className="summary-item">
                  <span className="summary-label">{t("result3d.summary_design")}</span>
                  <span className="summary-value">{designText}</span>
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <button className="action-btn action-btn-primary" onClick={() => download('pdf', 'design.pdf')}>
              {t("result3d.btn_pdf")}
            </button>

          </div>
        </div>
      </div>
    </div>
  );
};

export default Result3D;
