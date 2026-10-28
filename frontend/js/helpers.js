// أدوات مساعدة صغيرة.

/** انتظار مدة بالملّي ثانية (وعد). */
export const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** تحويل رقم إلى أرقام عربية (٠١٢٣…). */
const AR_DIGITS = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"];
export const toArabicDigits = (n) =>
  String(n).replace(/\d/g, (d) => AR_DIGITS[d]);

/** إعادة تشغيل حركة CSS عبر إزالة الصنف ثم إعادته (مع إجبار إعادة التدفق). */
export function restartAnimation(el, className) {
  el.classList.remove(className);
  void el.offsetWidth;
  el.classList.add(className);
}
