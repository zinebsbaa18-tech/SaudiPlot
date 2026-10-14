// Shared by LocationMapPicker (editable, with resize/rotate handles) and
// PlotMapView (read-only) so both draw the exact same land-plot rectangle
// from a center point + size + rotation.
//
// All "local" coordinates below are flat-earth meters relative to some
// reference point: x = east+, y = north+. Good enough at plot scale (tens
// to low hundreds of metres) — not meant for large-area survey accuracy.

const METERS_PER_DEG_LAT = 111320;

function metersPerDegLng(lat) {
  return METERS_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
}

/** Local meters offset (east+, north+) -> absolute {lat, lng}. */
export function offsetLatLng(refLat, refLng, dxMeters, dyMeters) {
  return {
    lat: refLat + dyMeters / METERS_PER_DEG_LAT,
    lng: refLng + dxMeters / metersPerDegLng(refLat),
  };
}

/** Absolute {lat, lng} -> local meters offset (east+, north+) from a reference point. */
export function toLocalMeters(refLat, refLng, lat, lng) {
  return {
    dx: (lng - refLng) * metersPerDegLng(refLat),
    dy: (lat - refLat) * METERS_PER_DEG_LAT,
  };
}

/**
 * Rotate a local (x, y) vector clockwise by angleDeg — 0 = north-up,
 * 90 = east, matching compass bearing convention.
 */
export function rotateLocal(x, y, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return { x: x * cos + y * sin, y: -x * sin + y * cos };
}

// Canonical unrotated corner sign multipliers, in a fixed order used
// everywhere a "corner index" is referenced: 0=TL, 1=TR, 2=BR, 3=BL.
const CORNER_SIGNS = [
  [-1, 1],
  [1, 1],
  [1, -1],
  [-1, -1],
];

/**
 * The 4 corners of the plot rectangle (center + size + rotation), in world
 * lat/lng, in the fixed TL/TR/BR/BL order matching CORNER_SIGNS.
 */
export function getRectangleCorners(centerLat, centerLng, widthM, heightM, rotationDeg = 0) {
  return CORNER_SIGNS.map(([sx, sy]) => {
    const local = rotateLocal((sx * widthM) / 2, (sy * heightM) / 2, rotationDeg);
    return offsetLatLng(centerLat, centerLng, local.x, local.y);
  });
}

/**
 * Build a rectangle (as GeoJSON geometry) representing the land plot
 * footprint, centered on the given point. `width` runs along the local
 * (pre-rotation) east-west axis, `height` along north-south, then the whole
 * shape is rotated by rotationDeg (clockwise, 0 = north-up). The deed only
 * gives two raw measurements and no orientation, so this is a best-effort
 * visual approximation, not a survey-accurate plot.
 */
export function buildPlotRectangle(lat, lng, widthM, heightM, rotationDeg = 0) {
  const corners = getRectangleCorners(lat, lng, widthM, heightM, rotationDeg);
  const ring = corners.map((c) => [c.lng, c.lat]);
  ring.push(ring[0]);
  return { type: "Polygon", coordinates: [ring] };
}

/**
 * Resize the rectangle by dragging one corner, keeping the opposite corner
 * fixed and the area constant (width * height stays equal to the rectangle's
 * area at the start of the drag). Whichever axis the cursor moved further
 * along (proportionally) drives the new size; the other dimension is
 * derived from the area constraint. Returns the new {centerLat, centerLng,
 * widthM, heightM} — rotation is untouched by a corner drag.
 */
export function resizeFromCorner({
  centerLat,
  centerLng,
  widthM,
  heightM,
  rotationDeg,
  cornerIndex,
  cursorLat,
  cursorLng,
  minDim = 3,
}) {
  const area = widthM * heightM;
  const oppositeIndex = (cornerIndex + 2) % 4;
  const fixed = getRectangleCorners(centerLat, centerLng, widthM, heightM, rotationDeg)[oppositeIndex];

  const { dx, dy } = toLocalMeters(fixed.lat, fixed.lng, cursorLat, cursorLng);
  const local = rotateLocal(dx, dy, -rotationDeg);
  const widthCandidate = Math.max(minDim, Math.abs(local.x));
  const heightCandidate = Math.max(minDim, Math.abs(local.y));

  const widthLogRatio = Math.abs(Math.log(widthCandidate / widthM));
  const heightLogRatio = Math.abs(Math.log(heightCandidate / heightM));

  let newWidth;
  let newHeight;
  if (widthLogRatio >= heightLogRatio) {
    newWidth = widthCandidate;
    newHeight = area / newWidth;
  } else {
    newHeight = heightCandidate;
    newWidth = area / newHeight;
  }

  const [sx, sy] = CORNER_SIGNS[oppositeIndex];
  const oppLocal = rotateLocal((sx * newWidth) / 2, (sy * newHeight) / 2, rotationDeg);
  const newCenter = offsetLatLng(fixed.lat, fixed.lng, -oppLocal.x, -oppLocal.y);

  return { centerLat: newCenter.lat, centerLng: newCenter.lng, widthM: newWidth, heightM: newHeight };
}

/** Compass bearing (0=N, 90=E, 180=S, 270=W) from center to a point. */
export function bearingFromCenter(centerLat, centerLng, lat, lng) {
  const { dx, dy } = toLocalMeters(centerLat, centerLng, lat, lng);
  let deg = (Math.atan2(dx, dy) * 180) / Math.PI;
  if (deg < 0) deg += 360;
  return deg;
}

/** Where to place the rotation handle: straight out from the top edge, in the plot's current orientation. */
export function getRotationHandlePosition(centerLat, centerLng, widthM, heightM, rotationDeg, offsetMeters) {
  const local = rotateLocal(0, heightM / 2 + offsetMeters, rotationDeg);
  return offsetLatLng(centerLat, centerLng, local.x, local.y);
}

/** Point offsetMeters away from center in a fixed compass direction (0=N, 90=E, 180=S, 270=W) — independent of the plot's own rotation, for the deed-boundary reference labels. */
export function pointAtBearing(centerLat, centerLng, bearingDeg, offsetMeters) {
  const rad = (bearingDeg * Math.PI) / 180;
  return offsetLatLng(centerLat, centerLng, offsetMeters * Math.sin(rad), offsetMeters * Math.cos(rad));
}
