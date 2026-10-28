// مدير الشاشات: تنقّل بانتقالات سلسة بين عناصر [data-screen].

export class Router {
  constructor(stageSelector = "#stage") {
    this.stage = document.querySelector(stageSelector);
    this.screens = new Map();
    for (const el of this.stage.querySelectorAll("[data-screen]")) {
      this.screens.set(el.dataset.screen, el);
    }
    this.current = null;
  }

  /** اسم الشاشة النشطة حالياً. */
  get activeName() {
    return this.current ? this.current.dataset.screen : null;
  }

  /**
   * إظهار شاشة بالاسم. يُخفي الحالية بانتقال ثم يُظهر الهدف.
   * @param {string} name
   */
  show(name) {
    const next = this.screens.get(name);
    if (!next || next === this.current) return;

    const prev = this.current;
    if (prev) {
      prev.classList.remove("is-active");
      prev.classList.add("is-leaving");
      prev.addEventListener(
        "transitionend",
        () => prev.classList.remove("is-leaving"),
        { once: true }
      );
    }

    // إجبار إعادة التدفق ليعمل الانتقال عند أول عرض
    void next.offsetWidth;
    next.classList.add("is-active");
    this.current = next;
    // ملاحظة: نستخدم data-active (وليس data-screen) حتى لا تتطابق الحاوية
    // مع محدِّد الأقسام [data-screen="..."].
    this.stage.dataset.active = name;
  }
}
