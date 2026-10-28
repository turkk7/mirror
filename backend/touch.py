# ============================================================================
# جسر طبقة اللمس — قراءة حسّاس ToF من المنفذ التسلسلي وبثّه للواجهة عبر SSE.
#
# لماذا في الباك-إند وليس المتصفّح؟ كروميوم على البوث snap معزول، ولا يملك slot
# لواجهة serial-port، فلا يستطيع فتح /dev/ttyACM0 عبر Web Serial. الباك-إند (بايثون،
# غير معزول، يعمل كـturkk ضمن مجموعة dialout) يفتح المنفذ ويبثّ الأسطر الخام كما هي،
# وتبقى كل المعايرة/كشف اللمسة/حقن النقرة في الواجهة (touch-serial.js).
#
# البروتوكول من ESP32:  R,<d_mm>,<v>  و  S,ready / S,err  — نبثّها كما وردت.
# ============================================================================

import glob
import logging
import threading
import time

log = logging.getLogger("touch")

BAUD = 115200


class TouchReader:
    """يقرأ المنفذ التسلسلي في خيط خلفي ويبثّ آخر سطر لمشتركي SSE.

    آمن الإنشاء دائماً: إن غابت pyserial أو المنفذ، يبقى الخيط يحاول بهدوء
    دون أن يُعطّل بقية الخادم.
    """

    def __init__(self, port: str = "", baud: int = BAUD):
        self._port = port          # فارغ = اكتشاف تلقائي
        self._baud = baud
        self._latest = None        # آخر سطر خام (str)
        self._seq = 0              # عدّاد يتزايد مع كل سطر جديد
        self._cond = threading.Condition()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._run, daemon=True, name="touch-serial").start()

    def _find_port(self):
        if self._port:
            return self._port
        for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
            hits = sorted(glob.glob(pattern))
            if hits:
                return hits[0]
        return None

    def _run(self) -> None:
        try:
            import serial  # pyserial — مؤجّل حتى لا يكسر الاستيراد على بيئة بلا الحزمة
        except Exception as exc:  # noqa: BLE001
            log.warning("طبقة اللمس معطّلة: pyserial غير متوفّرة (%s)", exc)
            return

        while True:
            port = self._find_port()
            if not port:
                time.sleep(2.0)
                continue
            try:
                ser = serial.Serial(port, self._baud, timeout=1.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("تعذّر فتح منفذ اللمس %s: %s", port, exc)
                time.sleep(2.0)
                continue

            log.info("طبقة اللمس: اتصلت بـ %s", port)
            try:
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("ascii", "replace").strip()
                    if not line or line[0] not in ("R", "S"):
                        continue
                    with self._cond:
                        self._latest = line
                        self._seq += 1
                        self._cond.notify_all()
            except Exception as exc:  # noqa: BLE001
                log.warning("انقطع منفذ اللمس %s: %s", port, exc)
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(1.5)  # ثم نعيد الاكتشاف والفتح

    def stream(self, timeout: float = 10.0):
        """مولّد Server-Sent Events: يطلق كل سطر جديد فور وروده.

        الحسّاس يبثّ ~40Hz باستمرار، لذا نادراً ما نحتاج نبضة الإبقاء.
        """
        last_seq = 0
        while True:
            with self._cond:
                if self._seq == last_seq:
                    self._cond.wait(timeout=timeout)
                if self._seq == last_seq:
                    yield ": keepalive\n\n"
                    continue
                last_seq = self._seq
                line = self._latest
            if line:
                yield f"data: {line}\n\n"
