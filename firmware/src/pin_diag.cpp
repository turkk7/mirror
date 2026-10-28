// ============================================================================
// اختبار أطراف موسّع — تشخيص بدون I2C.
// يفعّل سحباً داخلياً للأسفل على كل الأطراف الآمنة ويطبع أيّها يُقرأ HIGH.
// مقاومات السحب في الحسّاس (إلى VIN) ترفع الطرفين الموصّلين بـSDA/SCL.
//   - ظهور طرفين HIGH => الحسّاس مُغذّى، وهذان هما الطرفان الموصّلان فعلاً.
//   - لا شيء HIGH     => الحسّاس بلا طاقة (VIN/GND)، أو مقاوماته غير موجودة.
// الرفع:  pio run -e diag -t upload
// ============================================================================

#include <Arduino.h>

// أطراف آمنة للقراءة على ESP32-S3-N16R8 (نتجنّب USB 19/20، UART 43/44،
// وذاكرة PSRAM/Flash 26–37، وأطراف الإقلاع 0/45/46).
static const int PINS[] = {
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
  15, 16, 17, 18, 21, 38, 39, 40, 41, 42, 47, 48
};
static const int N = sizeof(PINS) / sizeof(PINS[0]);

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("--- مسح أطراف موسّع (ابحث عن الأطراف المرفوعة) ---");
  for (int i = 0; i < N; i++) pinMode(PINS[i], INPUT_PULLDOWN);
}

void loop() {
  Serial.print("HIGH على الأطراف: ");
  int found = 0;
  for (int i = 0; i < N; i++) {
    if (digitalRead(PINS[i])) {
      Serial.print("GPIO");
      Serial.print(PINS[i]);
      Serial.print(" ");
      found++;
    }
  }
  if (found == 0) Serial.print("(لا شيء — الحسّاس غالباً بلا طاقة)");
  Serial.println();
  delay(1500);
}
