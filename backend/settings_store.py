"""إعدادات المشغّل — محفوظة دائماً في ملف JSON (تبقى بعد إعادة التشغيل).

كل الإعدادات القابلة للتغيير من لوحة الأدمن تُدار هنا، محميّة بقفل.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


DEFAULTS = {
    "print_enabled": True,       # تفعيل الطباعة
    "copies": 1,                 # عدد النسخ لكل طباعة
    "timer_options": [5, 10, 15],  # مدد المؤقت المتاحة للضيف (ثوانٍ)
    "mirror_flip": True,         # قلب الصورة أفقياً
    "flash_enabled": True,       # وميض الفلاش
    "overlay": False,            # وجود إطار/شعار مرفوع
    "screensaver": "",           # رابط صورة شاشة التوقّف (ثيم المناسبة) — "" = معطّلة
    "admin_pin": "1234",         # رمز الدخول (يُهيّأ من البيئة أول مرة)
}

# الحقول المسموح تعديلها من الـ API (لا يشمل admin_pin — له مسار خاص)
EDITABLE = {
    "print_enabled", "copies",
    "timer_options", "mirror_flip", "flash_enabled",
}


class SettingsStore:
    def __init__(self, path: Path, default_pin: str):
        self._lock = threading.Lock()
        self._path = Path(path)
        self._data = dict(DEFAULTS)
        self._data["admin_pin"] = default_pin
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                self._data.update({k: v for k, v in saved.items() if k in self._data})
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # --- القراءة ---
    def public(self) -> dict:
        """الإعدادات التي تراها واجهة الضيف (بلا رمز)."""
        with self._lock:
            d = dict(self._data)
            d.pop("admin_pin", None)
            return d

    def get(self, key: str):
        with self._lock:
            return self._data.get(key)

    @property
    def pin(self) -> str:
        with self._lock:
            return self._data["admin_pin"]

    # --- التعديل ---
    # حدّ موثوق للتحقّق: الواجهة قابلة للتجاوز، فلا نثق بالقيم الواردة. القيم غير
    # الصالحة تُتجاهَل (يبقى الإعداد القديم) بدل حفظ قيمة تالفة.
    COPIES_MIN = 1
    COPIES_MAX = 5

    @staticmethod
    def _clean(key, value):
        """يتحقّق/يطبّع قيمة إعداد؛ None = غير صالحة فتُتجاهَل."""
        if key == "copies":
            try:
                n = int(value)
            except (TypeError, ValueError):
                return None
            return max(SettingsStore.COPIES_MIN, min(SettingsStore.COPIES_MAX, n))
        if key in ("print_enabled", "mirror_flip", "flash_enabled"):
            return bool(value)
        if key == "timer_options":
            if not isinstance(value, list):
                return None
            opts = []
            for x in value:
                try:
                    n = int(x)
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    opts.append(n)
            return opts or None  # قائمة فارغة/غير صالحة = إبقاء القديم
        return value

    def update(self, changes: dict) -> dict:
        with self._lock:
            for k, v in changes.items():
                if k not in EDITABLE:
                    continue
                cleaned = self._clean(k, v)
                if cleaned is not None:
                    self._data[k] = cleaned
            self._save()
            d = dict(self._data)
            d.pop("admin_pin", None)
            return d

    def set_overlay(self, exists: bool):
        with self._lock:
            self._data["overlay"] = exists
            self._save()

    def set_screensaver(self, url: str):
        """رابط صورة شاشة التوقّف ("" لإلغائها)."""
        with self._lock:
            self._data["screensaver"] = url or ""
            self._save()

    def change_pin(self, new_pin: str):
        with self._lock:
            self._data["admin_pin"] = str(new_pin)
            self._save()
