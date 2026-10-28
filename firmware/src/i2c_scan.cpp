// ============================================================================
// ماسح I2C — أداة تشخيص. يجرّب ترتيبَي SDA/SCL ويطبع عناوين أي جهاز يردّ.
// الرفع:  pio run -e scan -t upload   ثم القراءة من السيريال.
// المتوقّع مع VL53L1X سليم: يظهر 0x29.
// ============================================================================

#include <Arduino.h>
#include <Wire.h>

// أزواج (SDA, SCL) المرشّحة — نجرّبها بالتتابع لاستبعاد العكس أو الطرف الخطأ.
struct Pair { int sda; int scl; const char *name; };
static const Pair PAIRS[] = {
  {8, 9, "SDA=8  SCL=9"},
  {9, 8, "SDA=9  SCL=8"},
};

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("--- ماسح I2C (يجرّب عدة أطراف) ---");
}

void scanOn(const Pair &p) {
  Wire.end();
  Wire.begin(p.sda, p.scl);
  delay(50);
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print("  [");
      Serial.print(p.name);
      Serial.print("] وُجد جهاز على 0x");
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.print("  [");
    Serial.print(p.name);
    Serial.println("] لا شيء");
  }
}

void loop() {
  for (auto &p : PAIRS) scanOn(p);
  Serial.println("---");
  delay(2000);
}
