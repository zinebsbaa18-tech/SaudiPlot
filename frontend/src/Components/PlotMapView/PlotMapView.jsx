import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { buildPlotRectangle } from "../../utils/plotGeometry";
import "./PlotMapView.css";

// Same free, no-signup basemaps as LocationMapPicker.
const STREET_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
const SATELLITE_STYLE = {
  version: 8,
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

const RECT_SOURCE_ID = "land-plot-rect";
const RECT_FILL_LAYER = "land-plot-rect-fill";
const RECT_LINE_LAYER = "land-plot-rect-line";
const LABEL_SOURCE_ID = "land-plot-label";
const LABEL_LAYER = "land-plot-label-text";
const EMPTY_FEATURE_COLLECTION = { type: "FeatureCollection", features: [] };

/**
 * Read-only map showing the saved plot location and its footprint drawn to
 * scale (see buildPlotRectangle). No search, no "use my location", no
 * draggable marker — just a view. Lazy-imported by Result3D so MapLibre's
 * bundle cost is only paid when someone actually opens this tab.
 */
export default function PlotMapView({ lat, lng, widthM, heightM, rotationDeg = 0 }) {
  const { t } = useTranslation();
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [mapStyle, setMapStyle] = useState("street");

  const hasLocation = typeof lat === "number" && typeof lng === "number" && !Number.isNaN(lat) && !Number.isNaN(lng);
  const hasPlotSize = widthM > 0 && heightM > 0;
  const plotLabel = hasPlotSize ? t("map.dims_label", { width: widthM, height: heightM }) : "";

  useEffect(() => {
    if (!hasLocation || !containerRef.current) return undefined;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STREET_STYLE_URL,
      center: [lng, lat],
      zoom: 17,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    new maplibregl.Marker({ color: "#25231d" }).setLngLat([lng, lat]).addTo(map);

    function drawPlot() {
      if (!map.getSource(RECT_SOURCE_ID)) {
        map.addSource(RECT_SOURCE_ID, { type: "geojson", data: EMPTY_FEATURE_COLLECTION });
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
        map.addSource(LABEL_SOURCE_ID, { type: "geojson", data: EMPTY_FEATURE_COLLECTION });
        map.addLayer({
          id: LABEL_LAYER,
          type: "symbol",
          source: LABEL_SOURCE_ID,
          layout: { "text-field": ["get", "label"], "text-size": 13, "text-font": ["Noto Sans Regular"] },
          paint: { "text-color": "#3f2a1f", "text-halo-color": "#fff9ee", "text-halo-width": 1.6 },
        });
      }
      if (!hasPlotSize) return;
      map.getSource(RECT_SOURCE_ID).setData({
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: {}, geometry: buildPlotRectangle(lat, lng, widthM, heightM, rotationDeg) },
        ],
      });
      map.getSource(LABEL_SOURCE_ID).setData({
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: { label: plotLabel }, geometry: { type: "Point", coordinates: [lng, lat] } },
        ],
      });
    }

    map.on("load", drawPlot);
    map.on("style.load", drawPlot);

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Re-init when hasLocation flips false -> true (the store's coordinates
    // can still be loading on first mount) — lat/lng/size are otherwise
    // fixed for a given saved result, so they're deliberately left out.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasLocation]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(mapStyle === "street" ? STREET_STYLE_URL : SATELLITE_STYLE);
  }, [mapStyle]);

  if (!hasLocation) {
    return (
      <div className="plot-map-view plot-map-view--empty">
        <p>{t("map.no_saved_location")}</p>
      </div>
    );
  }

  return (
    <div className="plot-map-view">
      <div ref={containerRef} className="plot-map-view__map" />
      <div className="plot-map-view__style-toggle">
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
      {hasPlotSize && <div className="plot-map-view__dims-badge">{plotLabel}</div>}
    </div>
  );
}
