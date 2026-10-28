// ============================================================================
// برنامج اختبار حسّاس VL53L1X واحد (اختبار الطاولة)
// الهدف: التأكّد أن الحسّاس يقرأ إصبعاً ويتجاهل السطح قبل تركيب الاثنين.
//
// التوصيل: VIN→3V3, GND→GND, SDA→GPIO8, SCL→GPIO9, XSHUT يُترك فارغاً.
// الرفع:  pio run -e test-single -t upload
// المراقبة: pio device monitor -b 115200
//
// الخرج (قابل للقراءة + CSV):
//   d=<mm> valid=<0/1>
// ============================================================================

#include <Wire.h>
#include <SparkFun_VL53L1X.h>

static const int PIN_SDA = 8;
static const int PIN_SCL = 9;

// الحسّاس على العنوان الافتراضي 0x29، بلا XSHUT.
SFEVL53L1X sensor(Wire);

void setup() {
  Serial.begin(115200);
  delay(300);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);

  Serial.println("--- اختبار حسّاس واحد VL53L1X ---");
  if (sensor.begin() != 0) {
    Serial.println("فشل الإقلاع: تحقّق من الأسلاك/التغذية. (جرّب XSHUT→3V3)");
    while (1) delay(1000);     // توقّف — لا فائدة من المتابعة
  }
  Serial.println("تم الإقلاع. حرّك إصبعك أمام العدسة وراقب القيمة.");

  sensor.setDistanceModeShort();     // Short: أدق مع الإضاءة وحتى ~١.٣م
  sensor.setTimingBudgetInMs(20);
  sensor.setIntermeasurementPeriod(25);
  sensor.setROI(16, 16, 199);        // أوسع مجال ~27° (الحد الأقصى للشريحة). للمس نضيّقه لـ4×4.
  sensor.startRanging();
}

void loop() {
  if (!sensor.checkForDataReady()) return;

  uint16_t d = sensor.getDistance();          // مل‌م
  uint8_t  valid = (sensor.getRangeStatus() == 0) ? 1 : 0;
  sensor.clearInterrupt();

  Serial.print("d=");
  Serial.print(d);
  Serial.print("mm valid=");
  Serial.println(valid);
}
