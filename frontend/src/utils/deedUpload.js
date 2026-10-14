// Deed upload flow: client-side validation, then upload to OUR backend.
// All AI processing happens server-side -- no provider key in the browser.

import * as Api from "../Api/Api";

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB (matches the backend limit)
const ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png"];

export function validateFile(file) {
  const isAllowed =
    ALLOWED_TYPES.includes(file.type) ||
    file.type === "image/jpg" ||
    /\.(pdf|jpg|jpeg|png)$/i.test(file.name);

  if (!isAllowed) {
    throw new Error("نوع الملف غير مدعوم. الرجاء رفع ملف PDF أو JPG أو PNG.");
  }
  if (file.size > MAX_FILE_SIZE) {
    throw new Error("حجم الملف يتجاوز 20 ميغابايت. الرجاء رفع ملف أصغر.");
  }
}

const ERROR_MESSAGES = {
  extraction_unconfigured:
    "خدمة استخراج بيانات الصك غير مفعّلة على الخادم حالياً. يمكنك إدخال البيانات يدوياً.",
  quota_exceeded:
    "استخراج البيانات بالذكاء الاصطناعي غير متاح مؤقتاً (تجاوز حصة الاستخدام). أدخل بيانات الأرض يدوياً للمتابعة.",
  not_a_deed: "هذا الملف لا يبدو أنه صك عقاري سعودي. يرجى رفع صك الأرض أو مستند عقاري واضح.",
  provider_unreachable: "تعذر الوصول لخدمة التحليل. حاول مرة أخرى أو أدخل البيانات يدوياً.",
  provider_error: "تعذر تحليل الملف حالياً. حاول مرة أخرى أو أدخل البيانات يدوياً.",
  provider_bad_format: "فشل تحليل استجابة خدمة الذكاء الاصطناعي. حاول مرة أخرى.",
  file_too_large: "حجم الملف يتجاوز الحد المسموح. الرجاء رفع ملف أصغر.",
  unsupported_file_type: "نوع الملف غير مدعوم. الرجاء رفع ملف PDF أو JPG أو PNG.",
  backend_unreachable: "تعذر الاتصال بالخادم المحلي. تأكد من تشغيله ثم حاول مرة أخرى.",
};

export function messageForCode(code, fallback) {
  return ERROR_MESSAGES[code] || fallback;
}

// Uploads the deed and returns the server-side extraction result.
// onStatus mirrors the frozen overlay steps: reading -> sending -> parsing.
export async function analyzeDeedViaBackend(file, onStatus) {
  onStatus("reading");
  const project = await Api.ensureProject();
  onStatus("sending");
  const response = await Api.uploadDeed(project.id, file);
  onStatus("parsing");
  if (response.status !== "extracted" || !response.extraction) {
    const error = new Error(
      messageForCode(response.error_code, "تعذر استخراج بيانات الصك من الملف.")
    );
    error.code = response.error_code;
    throw error;
  }
  return response.extraction;
}
