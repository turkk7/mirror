// ============================================================================
// طبقة اللمس الافتراضية — برنامج الإنتاج لحسّاس VL53L1X واحد
// حسّاس واحد في أسفل إطار المرآة يصوّب للأعلى بمحاذاة سطح الشاشة (grazing).
// مسافته إلى اليد = الموضع على المحور الرأسي (Y). لا محور X — تُفترض النقرة عند
// منتصف العرض، فتصيب الأزرار العريضة المرصوفة عمودياً.
//
// مبدأ العمل (راجع docs/tof-touch-overlay.md — تحوّل الخطة إلى حسّاس واحد):
//   - XSHUT مربوط بالعتاد على 3V3 (الحسّاس يقظ دائماً)؛ البرنامج لا يقوده.
//   - الحسّاس على العنوان الافتراضي 0x29.
//   - البرنامج يرسل المسافة الخام فقط؛ المعايرة وكشف اللمسة في الواجهة (JS).
//
// البروتوكول (ESP32 → JS، 115200، أسطر CSV):
//   R,<d_mm>,<v>    إطار قياس: المسافة بالمليمتر، صلاحية القياس (0/1)
//   S,ready         جاهز بعد نجاح إقلاع الحسّاس
//   S,err           فشل إقلاع الحسّاس (تحقّق من الأسلاك/التغذية)
// ============================================================================

#include <Wire.h>
#include <SparkFun_VL53L1X.h>

// ---- أطراف التوصيل (حسّاس واحد؛ عدّلها حسب لوحتك) --------------------------
static const int PIN_SDA = 8;   // I2C SDA
static const int PIN_SCL = 9;   // I2C SCL
// XSHUT → 3V3 بالعتاد (لا يُقاد برمجياً). VIN→3V3، GND→GND. العنوان 0x29.

// ---- إعدادات القياس (راجع «القيود» في المستند) ----------------------------
// وضع Long: مدى حتى ٤م وإشارة أقوى على البُعد (يناسب البوث المظلم) — يصل أعلى الشاشة
// الطولية حيث كان Short يفقد اليد عند ~٤٤٥مم. Long يحتاج زمن قياس أطول لإشارة نظيفة.
static const uint16_t TIMING_BUDGET = 50;  // مل‌ث — أطول = إشارة أقوى على البُعد (~١٨Hz)
static const uint16_t INTER_PERIOD  = 55;  // مل‌ث — يجب ≥ timing budget
// مجال الرؤية واسع (16×16 ≈ 27°) ليلتقط اليد عبر عرض الشاشة. المحور X غير مهم (النقرة
// عند المنتصف). إن لزم لاحقاً تضييقه لتركيز الشعاع للأعلى.
static const uint8_t  ROI_X      = 16;
static const uint8_t  ROI_Y      = 16;
static const uint8_t  ROI_CENTER = 199;    // المركز البصري الافتراضي للـSPAD

// الحسّاس على العنوان الافتراضي 0x29، بلا XSHUT برمجي.
SFEVL53L1X sensor(Wire);

void setup() {
  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);                   // I2C سريع

  if (sensor.begin() != 0) {               // 0 = نجاح في مكتبة SparkFun
    Serial.println("S,err");               // فشل: تحقّق من الأسلاك/التغذية/XSHUT→3V3
    while (1) { delay(1000); Serial.println("S,err"); }
  }
  sensor.setDistanceModeLong();            // Long: مدى حتى ٤م، إشارة أقوى على البُعد (البوث مظلم)
  sensor.setTimingBudgetInMs(TIMING_BUDGET);
  sensor.setIntermeasurementPeriod(INTER_PERIOD);
  sensor.setROI(ROI_X, ROI_Y, ROI_CENTER);
  sensor.startRanging();

  Serial.println("S,ready");
}

void loop() {
  if (!sensor.checkForDataReady()) return;

  uint16_t d = sensor.getDistance();                   // مل‌م
  uint8_t  v = (sensor.getRangeStatus() == 0) ? 1 : 0; // 0 = قياس صالح
  sensor.clearInterrupt();

  Serial.print("R,");
  Serial.print(d); Serial.print(',');
  Serial.println(v);
}
