"""مخزن الصور الملتقطة (في الذاكرة) مع حذف فعلي للملفات — لحماية الخصوصية.

السياسة:
- صورة واحدة نشطة فقط: أي التقاطة أحدث تحذف السابقة فورًا (ملفها ومدخلها).
- عمر أقصى (ttl): تُحذف الصورة تلقائياً بعد انقضائه حتى بلا التقاطة جديدة.
لكل صورة: url (المسار)، ts (لحظة الالتقاط)، claimed (استُهلكت عبر /latest).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path


class PhotoStore:
    def __init__(self, ttl: float = 0, captures_dir: Path | None = None):
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, dict]" = OrderedDict()
        self._ttl = ttl  # ثوانٍ؛ 0 = بلا حد زمني
        self._captures_dir = Path(captures_dir) if captures_dir else None
        if ttl and ttl > 0:
            self._start_janitor()

    # --- أدوات داخلية ---
    def _delete_file(self, url: str) -> None:
        """يحذف ملف الصورة من القرص (الملفات الملتقطة فقط، لا العيّنات)."""
        if self._captures_dir and url.startswith("/captures/"):
            name = url.rsplit("/", 1)[-1]
            try:
                (self._captures_dir / name).unlink()
            except OSError:
                pass

    def _purge_all_locked(self) -> None:
        """يحذف كل الصور الحالية (ملفاتها ومدخلاتها). يُستدعى داخل القفل."""
        for item in self._items.values():
            self._delete_file(item["url"])
        self._items.clear()

    def _purge_expired(self) -> None:
        """يحذف الصور التي تجاوزت العمر الأقصى."""
        if not self._ttl:
            return
        now = time.time()
        with self._lock:
            for pid in [p for p, it in self._items.items() if now - it["ts"] > self._ttl]:
                self._delete_file(self._items[pid]["url"])
                del self._items[pid]

    def _start_janitor(self) -> None:
        def loop():
            while True:
                time.sleep(20)
                self._purge_expired()
        threading.Thread(target=loop, daemon=True).start()

    # --- واجهة عامة ---
    def add(self, photo_url: str) -> str:
        """يخزّن صورة جديدة بعد حذف كل ما سبقها (صورة واحدة نشطة)."""
        photo_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._purge_all_locked()  # الأحدث يزيح السابق فوراً
            self._items[photo_id] = {
                "url": photo_url,
                "ts": time.time(),
                "claimed": False,
            }
        return photo_id

    def get(self, photo_id: str) -> str | None:
        """رابط الصورة بالمعرّف (يعمل لصاحب الرابط ما دامت الصورة نشطة)."""
        with self._lock:
            item = self._items.get(photo_id)
            if not item:
                return None
            if self._ttl and time.time() - item["ts"] > self._ttl:
                return None
            return item["url"]

    def latest_id(self, ttl: float | None = None, unclaimed: bool = False) -> str | None:
        """معرّف آخر صورة للمشاركة عبر NFC (/latest) ضمن النافذة ولم تُستهلك."""
        with self._lock:
            if not self._items:
                return None
            pid = next(reversed(self._items))
            item = self._items[pid]
            if ttl is not None and (time.time() - item["ts"]) > ttl:
                return None
            if unclaimed and item["claimed"]:
                return None
            return pid

    def claim(self, photo_id: str) -> None:
        """يعلّم الصورة كمُستهلَكة (بعد تسليمها لأول لامس عبر /latest)."""
        with self._lock:
            item = self._items.get(photo_id)
            if item:
                item["claimed"] = True
