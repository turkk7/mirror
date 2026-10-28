"""حالة الجلسة: تتبّع عدد الصور الملتقطة مقابل حدّ الباقة.

نموذج الباقة = **عدد الالتقاطات** (كل ضغطة زناد تخصم، وتشمل إعادة الالتقاط).
الطباعة والمشاركة لا تخصمان من الباقة (إحصاء فقط).

تُدار في الذاكرة (كشك واحد لكل جهاز). محمية بقفل للتعامل مع الطلبات المتزامنة.
"""

from __future__ import annotations

import threading
import time


class Session:
    def __init__(self, photo_limit: int, duration_minutes: int):
        self._lock = threading.Lock()
        self.photo_limit = photo_limit
        self.duration_minutes = duration_minutes
        self.captures_used = 0  # أساس الباقة — يخصم مع كل التقاط
        self.prints_used = 0  # إحصاء الطباعة فقط
        self.shares_used = 0
        self.started_at = time.time()
        self.paused = False
        self.ended = False

    @property
    def remaining(self) -> int:
        return max(0, self.photo_limit - self.captures_used)

    @property
    def finished(self) -> bool:
        return self.ended or self.remaining <= 0

    def snapshot(self) -> dict:
        with self._lock:
            return self._state()

    def consume_capture(self) -> dict:
        """يسجّل التقاط صورة (يخصم من الباقة). يرجع (نجاح، لقطة الحالة)."""
        with self._lock:
            if self.ended or self.remaining <= 0:
                return {"ok": False, "reason": "package_finished", **self._state()}
            if self.paused:
                return {"ok": False, "reason": "paused", **self._state()}
            self.captures_used += 1
            return {"ok": True, **self._state()}

    def consume_print(self) -> dict:
        """يسجّل طباعة صورة (إحصاء فقط — لا يخصم من الباقة في نموذج الالتقاط).

        يُسمح بالطباعة للصورة الملتقطة حتى لو اكتملت الباقة، لأن الخصم تمّ عند
        الالتقاط. يُمنع فقط أثناء الإيقاف المؤقت.
        """
        with self._lock:
            if self.paused:
                return {"ok": False, "reason": "paused", **self._state()}
            self.prints_used += 1
            return {"ok": True, **self._state()}

    def consume_share(self) -> dict:
        """يسجّل مشاركة رقمية (لا يخصم من الباقة، للإحصاء فقط)."""
        with self._lock:
            self.shares_used += 1
            return {"ok": True, **self._state()}

    def reset(self, photo_limit: int | None = None,
              duration_minutes: int | None = None) -> dict:
        """بدء مناسبة جديدة."""
        with self._lock:
            if photo_limit is not None:
                self.photo_limit = photo_limit
            if duration_minutes is not None:
                self.duration_minutes = duration_minutes
            self.captures_used = 0
            self.prints_used = 0
            self.shares_used = 0
            self.started_at = time.time()
            self.paused = False
            self.ended = False
            return self._state()

    def extend(self, add_photos: int = 0, add_minutes: int = 0) -> dict:
        """تمديد الباقة دون تصفير."""
        with self._lock:
            self.photo_limit += max(0, add_photos)
            self.duration_minutes += max(0, add_minutes)
            if self.remaining > 0:
                self.ended = False
            return self._state()

    def set_paused(self, paused: bool) -> dict:
        with self._lock:
            self.paused = bool(paused)
            return self._state()

    def end(self) -> dict:
        with self._lock:
            self.ended = True
            return self._state()

    def _state(self) -> dict:
        elapsed = int(time.time() - self.started_at)
        total = self.duration_minutes * 60
        return {
            "limit": self.photo_limit,
            "used": self.captures_used,
            "prints": self.prints_used,
            "remaining": self.remaining,
            "shares": self.shares_used,
            "finished": self.ended or self.remaining <= 0,
            "paused": self.paused,
            "ended": self.ended,
            "session_minutes": self.duration_minutes,
            "elapsed_seconds": elapsed,
            "remaining_seconds": max(0, total - elapsed),
            "time_over": elapsed >= total,
        }
