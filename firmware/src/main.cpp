// ============================================================================
// طبقة اللمس الافتراضية — برنامج ESP32-S3
// حسّاسان VL53L1X (ToF) على ناقل I2C مشترك. يقيس الأول Y (عمودي V)، والثاني X (أفقي H).
//
// مبدأ العمل (راجع docs/tof-touch-overlay.md):
//   - كلا الحسّاسين يبدآن بالعنوان 0x29 → لا بد من XSHUT لإيقاظهما بالتتابع
//     وإعادة تعيين عنوان العمودي إلى 0x2A.
//   - البرنامج يقرأ المسافة الخام فقط ويرسلها؛ المعايرة وكشف اللمسة في الواجهة (JS).
//
// البروتوكول (ESP32 → JS، 115200، أسطر CSV):
//   R,<dv_mm>,<dh_mm>,<vv>,<vh>   إطار قياس: مسافة V، مسافة H، صلاحية V، صلاحية H (0/1)
//   S,ready                        جاهز بعد نجاح إقلاع الحسّاسين
//   S,err,<code>                   فشل إقلاع (code = أي حسّاس/مرحلة)
// ============================================================================

#include <Wire.h>
#include <SparkFun_VL53L1X.h>

// ---- أطراف التوصيل (عدّلها حسب لوحتك) -------------------------------------
static const int PIN_SDA     = 8;   // I2C SDA (+ مقاومة سحب 4.7kΩ)
static const int PIN_SCL     = 9;   // I2C SCL (+ مقاومة سحب 4.7kΩ)
static const int PIN_XSHUT_V = 4;   // تمكين الحسّاس العمودي (Y)
static const int PIN_XSHUT_H = 5;   // تمكين الحسّاس الأفقي (X)

// ---- إعدادات القياس (راجع «القيود» في المستند) ----------------------------
static const uint8_t  ADDR_V         = 0x2A; // عنوان الحسّاس العمودي بعد إعادة التعيين
// (الأفقي يبقى على 0x29 الافتراضي)
static const uint16_t TIMING_BUDGET  = 20;   // مل‌ث — قصير لاستجابة ~٥٠Hz
static const uint16_t INTER_PERIOD   = 25;   // مل‌ث — يجب ≥ timing budget
static const uint8_t  ROI_X          = 4;    // تضييق ROI (4 SPAD ≈ 15°) لتقليل تداخل الساعد
static const uint8_t  ROI_Y          = 4;    // (المدى الكامل 16 ≈ 27°)
static const uint8_t  ROI_CENTER     = 199;  // المركز البصري الافتراضي للـSPAD

// الحسّاسان: المُنشئ يربط طرف XSHUT فيتحكّم sensorOn/Off بالإيقاظ.
SFEVL53L1X sensorV(Wire, PIN_XSHUT_V, -1);
SFEVL53L1X sensorH(Wire, PIN_XSHUT_H, -1);

// آخر قياس مُخزَّن لكل محور (نرسل الأحدث دائماً).
static uint16_t lastDv = 0, lastDh = 0;
static uint8_t  lastVv = 0, lastVh = 0;

// تهيئة حسّاس واحد بالإعدادات المشتركة. يعيد true عند النجاح.
static bool configureSensor(SFEVL53L1X &s) {
  if (s.begin() != 0) return false;        // 0 = نجاح في مكتبة SparkFun
  s.setDistanceModeShort();                // Short أدق مع الإضاءة وحتى ~١.٣م (والبوث مظلم)
  s.setTimingBudgetInMs(TIMING_BUDGET);
  s.setIntermeasurementPeriod(INTER_PERIOD);
  s.setROI(ROI_X, ROI_Y, ROI_CENTER);      // تضييق مجال الرؤية
  s.startRanging();
  return true;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);                   // I2C سريع

  // 1) أطفئ الحسّاسين معاً عبر XSHUT حتى لا يتصادم العنوان 0x29.
  sensorV.sensorOff();
  sensorH.sensorOff();
  delay(10);

  // 2) أيقظ العمودي أولاً، هيّئه، ثم انقله إلى 0x2A.
  sensorV.sensorOn();
  delay(10);
  if (!configureSensor(sensorV)) { Serial.println("S,err,V"); }
  sensorV.setI2CAddress(ADDR_V);           // يبقى الأفقي على 0x29

  // 3) أيقظ الأفقي الآن وهيّئه على العنوان الافتراضي.
  sensorH.sensorOn();
  delay(10);
  if (!configureSensor(sensorH)) { Serial.println("S,err,H"); }

  Serial.println("S,ready");
}

void loop() {
  // الحسّاس العمودي يقود الوتيرة (كلاهما بنفس الميزانية الزمنية تقريباً).
  if (sensorV.checkForDataReady()) {
    lastDv = sensorV.getDistance();
    lastVv = (sensorV.getRangeStatus() == 0) ? 1 : 0; // 0 = قياس صالح
    sensorV.clearInterrupt();
  }
  if (sensorH.checkForDataReady()) {
    lastDh = sensorH.getDistance();
    lastVh = (sensorH.getRangeStatus() == 0) ? 1 : 0;
    sensorH.clearInterrupt();

    // نرسل إطاراً عند كل قياس جديد من الأفقي (يضمن تزامن القيمتين الأحدث).
    Serial.print("R,");
    Serial.print(lastDv); Serial.print(',');
    Serial.print(lastDh); Serial.print(',');
    Serial.print(lastVv); Serial.print(',');
    Serial.println(lastVh);
  }
}
