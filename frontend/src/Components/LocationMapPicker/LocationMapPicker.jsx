import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  buildPlotRectangle,
  getRectangleCorners,
  resizeFromCorner,
  bearingFromCenter,
  getRotationHandlePosition,
  pointAtBearing,
} from "../../utils/plotGeometry";
import "./LocationMapPicker.css";

// Free, no-signup basemaps only:
// - OpenFreeMap "liberty" — a full vector style, unlimited free hosting.
// - Esri World Imagery — free raster satellite tiles, no key required.
const STREET_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
const SATELLITE_STYLE = {
  version: 8,
  // Reuse OpenFreeMap's free public glyph (font) server so labels still
  // render in satellite mode, which has no vector tiles of its own to
  // source fonts from.
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {
    esri: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Esri, Maxar, Earthstar Geographics",
    },
  },
  layers: [{ id: "esri", type: "raster", source: "esri" }],
};

const DEFAULT_CENTER = { lat: 24.7136, lng: 46.6753 }; // Riyadh
const DEFAULT_ZOOM = 11;
const PICKED_ZOOM = 17;

const RECT_SOURCE_ID = "land-plot-rect";
const RECT_FILL_LAYER = "land-plot-rect-fill";
const RECT_LINE_LAYER = "land-plot-rect-line";
const LABEL_SOURCE_ID = "land-plot-label";
const LABEL_LAYER = "land-plot-label-text";
const HANDLE_LINE_SOURCE_ID = "rotate-handle-line";
const HANDLE_LINE_LAYER = "rotate-handle-line-layer";
const BOUNDARY_SOURCE_ID = "deed-boundary-labels";
const BOUNDARY_LAYER = "deed-boundary-label-text";

const EMPTY_FC = { type: "FeatureCollection", features: [] };
const CORNER_CURSORS = ["nwse-resize", "nesw-resize", "nwse-resize", "nesw-resize"];
const BOUNDARY_KEYS = [
  { key: "north", bearing: 0 },
  { key: "east", bearing: 90 },
  { key: "south", bearing: 180 },
  { key: "west", bearing: 270 },
];

function makeHandleEl(className, cursor) {
  const el = document.createElement("div");
  el.className = className;
  el.style.cursor = cursor;
  return el;
}

// Always mounted only while the picker should be visible (parent controls
// this), which is also what keeps MapLibre out of the initial bundle: it's
// lazy-imported and only fetched once the user opens the map.
export default function LocationMapPicker({
  initialLat,
  initialLng,
  landWidth,
  landHeight,
  initialRotationDeg = 0,
  deedBoundaries, // optional { north, south, east, west } numbers, in metres
  onConfirm, // ({ lat, lng, widthM, heightM, rotationDeg }) => void
  onClose,
}) {
  const { t, i18n } = useTranslation();
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const centerMarkerRef = useRef(null);
  const cornerMarkersRef = useRef([]);
  const rotateMarkerRef = useRef(null);
  const searchAbortRef = useRef(null);

  const [mapStyle, setMapStyle] = useState("street");

  const initialWidthM = Number(landWidth) || 0;
  const initialHeightM = Number(landHeight) || 0;
  const hasFixedSize = initialWidthM > 0 && initialHeightM > 0;

  const [plot, setPlot] = useState(() => {
    if (initialLat == null || initialLng == null) return null;
    return {
      centerLat: initialLat,
      centerLng: initialLng,
      widthM: initialWidthM,
      heightM: initialHeightM,
      rotationDeg: initialRotationDeg,
    };
  });
  // Authoritative, synchronously-mutable copy for the native drag handlers
  // (MapLibre fires 'drag' events faster than React re-renders would keep
  // up with) — `plot` state stays in sync for the footer/UI to read.
  const plotRef = useRef(plot);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;

    const startCenter = plotRef.current
      ? { lat: plotRef.current.centerLat, lng: plotRef.current.centerLng }
      : DEFAULT_CENTER;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STREET_STYLE_URL,
      center: [startCenter.lng, startCenter.lat],
      zoom: plotRef.current ? PICKED_ZOOM : DEFAULT_ZOOM,
      attributionControl: { compact: true },
      dragRotate: false, // keep north-up always, so the static north arrow stays accurate
      touchPitch: false,
    });
    mapRef.current = map;
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");

    const centerMarker = new maplibregl.Marker({ draggable: true, color: "#25231d" }).setLngLat([
      startCenter.lng,
      startCenter.lat,
    ]);
    if (plotRef.current) centerMarker.addTo(map);
    centerMarkerRef.current = centerMarker;

    const cornerMarkers = CORNER_CURSORS.map(
      (cursor) => new maplibregl.Marker({ element: makeHandleEl("map-picker__corner-handle", cursor) })
    );
    cornerMarkersRef.current = cornerMarkers;
    const rotateMarker = new maplibregl.Marker({
      element: makeHandleEl("map-picker__rotate-handle", "grab"),
    });
    rotateMarkerRef.current = rotateMarker;

    function ensureLayers() {
      if (!map.getSource(RECT_SOURCE_ID)) {
        map.addSource(RECT_SOURCE_ID, { type: "geojson", data: EMPTY_FC });
        map.addLayer({
          id: RECT_FILL_LAYER,
          type: "fill",
          source: RECT_SOURCE_ID,
          paint: { "fill-color": "#9d5b3e", "fill-opacity": 0.22 },
        });
        map.addLayer({
          id: RECT_LINE_LAYER,
          type: "line",
          source: RECT_SOURCE_ID,
          paint: { "line-color": "#9d5b3e", "line-width": 2.5, "line-dasharray": [2, 1] },
        });
      }
      if (!map.getSource(LABEL_SOURCE_ID)) {
        map.addSource(LABEL_SOURCE_ID, { type: "geojson", data: EMPTY_FC });
        map.addLayer({
          id: LABEL_LAYER,
          type: "symbol",
          source: LABEL_SOURCE_ID,
          layout: { "text-field": ["get", "label"], "text-size": 13, "text-font": ["Noto Sans Regular"] },
          paint: { "text-color": "#3f2a1f", "text-halo-color": "#fff9ee", "text-halo-width": 1.6 },
        });
      }
      if (!map.getSource(HANDLE_LINE_SOURCE_ID)) {
        map.addSource(HANDLE_LINE_SOURCE_ID, { type: "geojson", data: EMPTY_FC });
        map.addLayer({
          id: HANDLE_LINE_LAYER,
          type: "line",
          source: HANDLE_LINE_SOURCE_ID,
          paint: { "line-color": "#505632", "line-width": 1.5, "line-dasharray": [1, 1] },
        });
      }
      if (!map.getSource(BOUNDARY_SOURCE_ID)) {
        map.addSource(BOUNDARY_SOURCE_ID, { type: "geojson", data: EMPTY_FC });
        map.addLayer({
          id: BOUNDARY_LAYER,
          type: "symbol",
          source: BOUNDARY_SOURCE_ID,
          layout: { "text-field": ["get", "label"], "text-size": 12, "text-font": ["Noto Sans Regular"] },
          paint: { "text-color": "#1f4e79", "text-halo-color": "#fff9ee", "text-halo-width": 1.6 },
        });
      }
    }

    function redraw() {
      ensureLayers();
      const p = plotRef.current;
      const rectSource = map.getSource(RECT_SOURCE_ID);
      const labelSource = map.getSource(LABEL_SOURCE_ID);
      const lineSource = map.getSource(HANDLE_LINE_SOURCE_ID);
      const boundarySource = map.getSource(BOUNDARY_SOURCE_ID);

      if (!p || p.widthM <= 0 || p.heightM <= 0) {
        rectSource?.setData(EMPTY_FC);
        labelSource?.setData(EMPTY_FC);
        lineSource?.setData(EMPTY_FC);
        boundarySource?.setData(EMPTY_FC);
        cornerMarkers.forEach((m) => m.remove());
        rotateMarker.remove();
        return;
      }

      const { centerLat, centerLng, widthM, heightM, rotationDeg } = p;
      const corners = getRectangleCorners(centerLat, centerLng, widthM, heightM, rotationDeg);

      rectSource?.setData({
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: buildPlotRectangle(centerLat, centerLng, widthM, heightM, rotationDeg) }],
      });

      const label = t("map.dims_label", { width: Math.round(widthM * 10) / 10, height: Math.round(heightM * 10) / 10 });
      labelSource?.setData({
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: { label }, geometry: { type: "Point", coordinates: [centerLng, centerLat] } }],
      });

      corners.forEach((c, i) => {
        cornerMarkers[i].setLngLat([c.lng, c.lat]);
        if (!cornerMarkers[i].getElement().isConnected) cornerMarkers[i].addTo(map);
      });

      const rotateOffset = Math.max(widthM, heightM) * 0.18 + 6;
      const rotatePos = getRotationHandlePosition(centerLat, centerLng, widthM, heightM, rotationDeg, rotateOffset);
      rotateMarker.setLngLat([rotatePos.lng, rotatePos.lat]);
      if (!rotateMarker.getElement().isConnected) rotateMarker.addTo(map);

      const topMid = getRectangleCorners(centerLat, centerLng, widthM, heightM, rotationDeg);
      const topMidPoint = {
        lat: (topMid[0].lat + topMid[1].lat) / 2,
        lng: (topMid[0].lng + topMid[1].lng) / 2,
      };
      lineSource?.setData({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: [[topMidPoint.lng, topMidPoint.lat], [rotatePos.lng, rotatePos.lat]] },
          },
        ],
      });

      if (deedBoundaries) {
        const boundaryOffset = Math.max(widthM, heightM) / 2 + 10;
        const features = BOUNDARY_KEYS.filter(({ key }) => deedBoundaries[key] > 0).map(({ key, bearing }) => {
          const pos = pointAtBearing(centerLat, centerLng, bearing, boundaryOffset);
          const label = t("map.boundary_label", { dir: t(`map.dir_${key}`), value: deedBoundaries[key] });
          return { type: "Feature", properties: { label }, geometry: { type: "Point", coordinates: [pos.lng, pos.lat] } };
        });
        boundarySource?.setData({ type: "FeatureCollection", features });
      }
    }

    function commitPlot(next) {
      plotRef.current = next;
      setPlot(next);
      redraw();
    }

    map.on("load", redraw);
    map.on("style.load", redraw);

    centerMarker.on("drag", () => {
      const { lat, lng } = centerMarker.getLngLat();
      const prev = plotRef.current;
      commitPlot(prev ? { ...prev, centerLat: lat, centerLng: lng } : { centerLat: lat, centerLng: lng, widthM: 0, heightM: 0, rotationDeg: 0 });
    });

    map.on("click", (e) => {
      const { lat, lng } = e.lngLat;
      centerMarker.setLngLat([lng, lat]);
      if (!centerMarker.getElement().isConnected) centerMarker.addTo(map);
      const prev = plotRef.current;
      commitPlot(
        prev
          ? { ...prev, centerLat: lat, centerLng: lng }
          : { centerLat: lat, centerLng: lng, widthM: initialWidthM, heightM: initialHeightM, rotationDeg: initialRotationDeg }
      );
    });

    cornerMarkers.forEach((marker, index) => {
      marker.on("drag", () => {
        const p = plotRef.current;
        if (!p) return;
        const { lat, lng } = marker.getLngLat();
        const next = resizeFromCorner({
          centerLat: p.centerLat,
          centerLng: p.centerLng,
          widthM: p.widthM,
          heightM: p.heightM,
          rotationDeg: p.rotationDeg,
          cornerIndex: index,
          cursorLat: lat,
          cursorLng: lng,
        });
        commitPlot({ ...p, ...next });
        centerMarker.setLngLat([next.centerLng, next.centerLat]);
      });
    });

    rotateMarker.on("drag", () => {
      const p = plotRef.current;
      if (!p) return;
      const { lat, lng } = rotateMarker.getLngLat();
      const rotationDeg = bearingFromCenter(p.centerLat, p.centerLng, lat, lng);
      commitPlot({ ...p, rotationDeg });
    });

    mapRef.current.__redraw = redraw;

    return () => {
      map.remove();
      mapRef.current = null;
      centerMarkerRef.current = null;
      cornerMarkersRef.current = [];
      rotateMarkerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- init once on mount only
  }, []);

  // Swap basemap without tearing the map down.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(mapStyle === "street" ? STREET_STYLE_URL : SATELLITE_STYLE);
  }, [mapStyle]);

  function flyTo(lat, lng, zoom = PICKED_ZOOM) {
    const map = mapRef.current;
    const centerMarker = centerMarkerRef.current;
    if (!map || !centerMarker) return;
    centerMarker.setLngLat([lng, lat]);
    if (!centerMarker.getElement().isConnected) centerMarker.addTo(map);
    map.flyTo({ center: [lng, lat], zoom });
    const prev = plotRef.current;
    const next = prev
      ? { ...prev, centerLat: lat, centerLng: lng }
      : { centerLat: lat, centerLng: lng, widthM: initialWidthM, heightM: initialHeightM, rotationDeg: initialRotationDeg };
    plotRef.current = next;
    setPlot(next);
    map.__redraw?.();
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setGeoError(t("map.geo_unsupported"));
      return;
    }
    setLocating(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        flyTo(pos.coords.latitude, pos.coords.longitude);
      },
      () => {
        setLocating(false);
        setGeoError(t("map.geo_denied"));
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  // Debounced free-text search via OSM's free Nominatim geocoder. Only
  // schedules a fetch (and only setState from inside its callback) — the
  // "query too short" case is handled at render time via `visibleResults`
  // below instead of clearing state synchronously from the effect.
  useEffect(() => {
    if (query.trim().length < 3) {
      searchAbortRef.current?.abort();
      return undefined;
    }
    const timer = setTimeout(async () => {
      searchAbortRef.current?.abort();
      const controller = new AbortController();
      searchAbortRef.current = controller;
      setSearching(true);
      try {
        const url = `https://nominatim.openstreetmap.org/search?format=json&limit=5&accept-language=${i18n.language}&countrycodes=sa&q=${encodeURIComponent(query)}`;
        const res = await fetch(url, { signal: controller.signal });
        const data = await res.json();
        setResults(data);
      } catch {
        // aborted or offline — leave previous results
      } finally {
        setSearching(false);
      }
    }, 450);
    return () => clearTimeout(timer);
  }, [query, i18n.language]);

  const visibleResults = query.trim().length < 3 ? [] : results;
  const hasPlotSize = !!plot && plot.widthM > 0 && plot.heightM > 0;
  const areaM2 = hasPlotSize ? Math.round(plot.widthM * plot.heightM) : 0;
  const perimeterM = hasPlotSize ? Math.round(2 * (plot.widthM + plot.heightM)) : 0;

  return (
    <div className="map-picker-overlay" role="dialog" aria-modal="true" aria-label={t("map.title")}>
      <div className="map-picker">
        <header className="map-picker__header">
          <div>
            <h2 className="map-picker__title">{t("map.title")}</h2>
            {hasFixedSize && (
              <p className="map-picker__dims-badge">
                {t("map.dims_badge", { width: landWidth, height: landHeight })}
              </p>
            )}
          </div>
          <button type="button" className="map-picker__close" onClick={onClose} aria-label={t("map.close")}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        {hasFixedSize && (
          <p className="map-picker__hint">{t("map.reshape_hint")}</p>
        )}

        <div className="map-picker__search-row">
          <div className="map-picker__search">
            <svg className="map-picker__search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none">
              <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
              <path d="M20 20l-4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              className="map-picker__search-input"
              placeholder={t("map.search_placeholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {visibleResults.length > 0 && (
              <ul className="map-picker__results">
                {visibleResults.map((r) => (
                  <li key={r.place_id}>
                    <button
                      type="button"
                      onClick={() => {
                        flyTo(Number(r.lat), Number(r.lon), 15);
                        setQuery(r.display_name);
                        setResults([]);
                      }}
                    >
                      {r.display_name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {searching && <span className="map-picker__search-spinner" aria-hidden="true" />}
          </div>

          <button type="button" className="map-picker__locate-btn" onClick={useMyLocation} disabled={locating}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
              <path
                d="M12 2v3M12 19v3M2 12h3M19 12h3"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
            {locating ? t("map.locating") : t("map.use_my_location")}
          </button>
        </div>

        {geoError && <p className="map-picker__geo-error">{geoError}</p>}

        <div className="map-picker__map-wrap">
          <div ref={containerRef} className="map-picker__map" />
          <div className="map-picker__north-arrow" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none">
              <path d="M12 2v20M12 2l-5 8h10z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
            <span>{t("map.north")}</span>
          </div>
          {hasPlotSize && (
            <div className="map-picker__area-badge">
              {t("map.area_perimeter", { area: areaM2, perimeter: perimeterM })}
            </div>
          )}
          <div className="map-picker__style-toggle">
            <button
              type="button"
              className={mapStyle === "street" ? "is-active" : ""}
              onClick={() => setMapStyle("street")}
            >
              {t("map.style_street")}
            </button>
            <button
              type="button"
              className={mapStyle === "satellite" ? "is-active" : ""}
              onClick={() => setMapStyle("satellite")}
            >
              {t("map.style_satellite")}
            </button>
          </div>
        </div>

        <footer className="map-picker__footer">
          <span className="map-picker__coords">
            {plot
              ? t("map.selected_coords", { lat: plot.centerLat.toFixed(6), lon: plot.centerLng.toFixed(6) })
              : t("map.no_selection")}
          </span>
          <div className="map-picker__actions">
            <button type="button" className="map-picker__cancel" onClick={onClose}>
              {t("map.cancel")}
            </button>
            <button
              type="button"
              className="map-picker__confirm"
              disabled={!plot}
              onClick={() =>
                plot &&
                onConfirm({
                  lat: plot.centerLat,
                  lng: plot.centerLng,
                  widthM: plot.widthM,
                  heightM: plot.heightM,
                  rotationDeg: plot.rotationDeg,
                })
              }
            >
              {t("map.confirm")}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
