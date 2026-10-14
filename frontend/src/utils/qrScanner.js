import jsQR from "jsqr";

const PDF_PAGE_SCAN_LIMIT = 3;
const PDF_RENDER_SCALE = 2.5;

/**
 * Try to parse GPS coordinates out of a QR code's decoded text.
 * Handles URL params, JSON objects, and bare decimal coordinate pairs.
 */
function tryParseCoordinates(text) {
  // URL with lat/lng query params
  try {
    const url = new URL(text);
    const lat =
      url.searchParams.get("lat") ||
      url.searchParams.get("latitude") ||
      url.searchParams.get("Lat");
    const lng =
      url.searchParams.get("lng") ||
      url.searchParams.get("lon") ||
      url.searchParams.get("longitude") ||
      url.searchParams.get("Lng");
    if (lat && lng) {
      return { lat: parseFloat(lat), lng: parseFloat(lng), from: "url_params" };
    }
  } catch {
    // not a valid URL, continue
  }

  // JSON object
  try {
    const obj = JSON.parse(text);
    const lat = obj.lat ?? obj.latitude ?? obj.Lat ?? obj.Latitude;
    const lng =
      obj.lng ?? obj.longitude ?? obj.lon ?? obj.Lng ?? obj.Longitude;
    if (lat != null && lng != null) {
      return {
        lat: parseFloat(lat),
        lng: parseFloat(lng),
        from: "json",
      };
    }
  } catch {
    // not JSON, continue
  }

  // Bare decimal pair: "24.7890, 46.6543" or "24.789 46.654"
  const match = text.match(/(-?\d{1,3}\.\d{4,})[,\s]+(-?\d{1,3}\.\d{4,})/);
  if (match) {
    const lat = parseFloat(match[1]);
    const lng = parseFloat(match[2]);
    // Sanity-check: must be inside the Arabian Peninsula bounding box
    if (lat > 15 && lat < 35 && lng > 34 && lng < 56) {
      return { lat, lng, from: "decimal_pattern" };
    }
  }

  return null;
}

/**
 * Run jsQR on a sub-region of any canvas-drawable source (image or canvas).
 */
function scanRegion(source, sx, sy, sw, sh) {
  const canvas = document.createElement("canvas");
  canvas.width = sw;
  canvas.height = sh;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, sw, sh);
  const imgData = ctx.getImageData(0, 0, sw, sh);
  const result = jsQR(imgData.data, imgData.width, imgData.height, {
    inversionAttempts: "attemptBoth",
  });
  return result?.data ?? null;
}

/**
 * Scan the full source plus each of its four quadrants — improves detection
 * when multiple QR codes sit in different corners of the same page.
 */
function scanAllRegions(source, w, h, found) {
  const regions = [
    [0, 0, w, h],
    [0, 0, Math.ceil(w / 2), Math.ceil(h / 2)],
    [Math.floor(w / 2), 0, Math.ceil(w / 2), Math.ceil(h / 2)],
    [0, Math.floor(h / 2), Math.ceil(w / 2), Math.ceil(h / 2)],
    [Math.floor(w / 2), Math.floor(h / 2), Math.ceil(w / 2), Math.ceil(h / 2)],
  ];
  for (const [sx, sy, sw, sh] of regions) {
    const code = scanRegion(source, sx, sy, sw, sh);
    if (code) found.add(code);
  }
}

function loadImage(file) {
  return new Promise((resolve) => {
    const img = new Image();
    const objectUrl = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(null);
    };
    img.src = objectUrl;
  });
}

let workerConfigured = false;

async function getPdfjs() {
  const pdfjsLib = await import("pdfjs-dist");
  if (!workerConfigured) {
    const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
    pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
    workerConfigured = true;
  }
  return pdfjsLib;
}

/**
 * Render each page of a PDF to an offscreen canvas and collect QR codes
 * found across all pages (capped for performance).
 */
async function scanPdf(file) {
  const found = new Set();
  try {
    const pdfjsLib = await getPdfjs();
    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    const pageCount = Math.min(pdf.numPages, PDF_PAGE_SCAN_LIMIT);

    for (let pageNum = 1; pageNum <= pageCount; pageNum++) {
      const page = await pdf.getPage(pageNum);
      const viewport = page.getViewport({ scale: PDF_RENDER_SCALE });

      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext("2d");
      await page.render({ canvasContext: ctx, viewport }).promise;

      scanAllRegions(canvas, canvas.width, canvas.height, found);
    }
  } catch {
    // PDF failed to render/parse — return whatever was found (likely nothing)
  }
  return found;
}

/**
 * Scan all QR codes from a deed file (image or PDF).
 * For images: scans the raster directly.
 * For PDFs: renders each page to canvas first, then scans (up to 3 pages).
 *
 * Returns { codes: string[], coordinates: { lat, lng, from } | null }
 */
export async function scanQRCodesFromImage(file) {
  const found = new Set();

  if (file.type === "application/pdf") {
    const pdfCodes = await scanPdf(file);
    pdfCodes.forEach((code) => found.add(code));
  } else {
    const img = await loadImage(file);
    if (img) {
      scanAllRegions(img, img.naturalWidth, img.naturalHeight, found);
    }
  }

  const codes = [...found];
  let coordinates = null;
  for (const code of codes) {
    const coord = tryParseCoordinates(code);
    if (coord) {
      coordinates = coord;
      break;
    }
  }

  return { codes, coordinates };
}
