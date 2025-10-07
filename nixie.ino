#include <Arduino.h>
#include "EasyNixie.h"

// ---------- Wiring ----------
#define PIN_OUT_EN 3
#define PIN_SHCP   4
#define PIN_STCP   2
#define PIN_DSIN   5

EasyNixie nixie(PIN_OUT_EN, PIN_SHCP, PIN_STCP, PIN_DSIN);

// ---------- Config ----------
static const uint8_t  NUM_TUBES        = 6;
static const unsigned BAUD             = 9600;
static const uint8_t  ATTRACT_DIM      = 0;      // 0 = brightest
static const unsigned long ATTRACT_MS  = 50;
static const unsigned long IDLE_PARSE_MS = 30;

// ---------- State ----------
struct TubeState {
  uint8_t digit;
  uint8_t r,g,b;    // requested RGB from MPF
  bool    hv, comma;
  uint16_t dim;
};
TubeState tubes[NUM_TUBES];
bool   gotFirstCommand = false;
char   buf[192];
size_t blen = 0;
unsigned long lastByteAt = 0, lastAttract = 0;

// ---------- Helpers ----------
static inline uint8_t clamp255(int v){ return (v<0)?0:(v>255)?255:v; }
static inline void setBrightness(uint8_t dim){ analogWrite(PIN_OUT_EN, dim); }
static inline void setTube(uint8_t i, uint8_t d, uint8_t r, uint8_t g, uint8_t b, bool hv, bool comma=false, uint16_t dim=0){
  if (i<NUM_TUBES) tubes[i] = { d, r, g, b, hv, comma, dim };
}

// Map arbitrary RGB to the nearest EasyNixie color macro.
// Library defines: BLUE, GREEN, RED, WHITE, RuB, RuG, BuG.
static uint8_t rgbToEnum(uint8_t r, uint8_t g, uint8_t b){
  struct Pal { uint8_t r,g,b, ev; };
  const Pal pal[] = {
    {  0,   0, 255, EASY_NIXIE_BLUE  },
    {  0, 255,   0, EASY_NIXIE_GREEN },
    {255,   0,   0, EASY_NIXIE_RED   },
    {255, 255, 255, EASY_NIXIE_WHITE },
    {255,   0, 255, EASY_NIXIE_RuB   }, // ≈ magenta
    {255, 255,   0, EASY_NIXIE_RuG   }, // ≈ yellow/orange
    {  0, 255, 255, EASY_NIXIE_BuG   }  // ≈ cyan
  };

  // Exact match shortcut
  for (uint8_t i=0; i<sizeof(pal)/sizeof(pal[0]); i++){
    if (pal[i].r==r && pal[i].g==g && pal[i].b==b) return pal[i].ev;
  }
  // Nearest color (Euclidean distance)
  uint32_t bestD = 0xFFFFFFFF; uint8_t bestE = pal[0].ev;
  for (uint8_t i=0; i<sizeof(pal)/sizeof(pal[0]); i++){
    int dr = int(r) - pal[i].r;
    int dg = int(g) - pal[i].g;
    int db = int(b) - pal[i].b;
    uint32_t d = uint32_t(dr*dr) + uint32_t(dg*dg) + uint32_t(db*db);
    if (d < bestD){ bestD = d; bestE = pal[i].ev; }
  }
  return bestE;
}

// ---------- Render (farthest -> nearest, then latch) ----------
static void render(){
  for (int i = NUM_TUBES - 1; i >= 0; --i){
    auto &t = tubes[i];
    uint8_t shown = (t.hv && t.digit <= 9) ? t.digit : 0;
    uint8_t col   = rgbToEnum(t.r, t.g, t.b);
    nixie.SetNixie(shown, col, t.hv, t.comma, t.dim);
  }
  nixie.Latch();
}

// Trim helpers
static void rtrim(char* s){
  int n = strlen(s);
  while (n>0 && (s[n-1]=='\r' || s[n-1]=='\n' || s[n-1]==' ' || s[n-1]=='\t')) s[--n]=0;
}
static char* ltrim(char* s){ while(*s==' '||*s=='\t') ++s; return s; }

// Parse "N,idx,digit,r,g,b,dim"
static bool parseNLine(char* p){
  char* save=nullptr;
  strtok_r(p,",",&save); // eat 'N'
  int f[6];
  for (int i=0;i<6;i++){
    char* tok=strtok_r(nullptr,",",&save);
    if(!tok) return false;
    while(*tok==' '||*tok=='\t') ++tok;
    f[i]=atoi(tok);
  }

  uint8_t idx   = (uint8_t)f[0];
  uint8_t digit = (uint8_t)f[1];
  uint8_t r     = (uint8_t)clamp255(f[2]);
  uint8_t g     = (uint8_t)clamp255(f[3]);
  uint8_t b     = (uint8_t)clamp255(f[4]);
  uint8_t dim   = (uint8_t)f[5];

  if (idx >= NUM_TUBES) return false;

  gotFirstCommand = true;
  setBrightness(dim);

  bool hv = (digit <= 9);
  setTube(idx, hv ? digit : 0, r, g, b, hv, /*comma=*/false, /*dim=*/dim);
  render();
  return true;
}

// ---------- Serial line handler ----------
static void handleLine(char* raw){
  rtrim(raw);
  char* p = ltrim(raw);
  if (!*p) return;

  // Easter egg
  if (p[0]=='4' && p[1]=='2' && p[2]==0){
    Serial.println(F("so long and thanks for all the fish"));
    return;
  }

  // 'A' -> return to Arduino-side attract
  if ((p[0]=='A' || p[0]=='a') && p[1]==0){
    gotFirstCommand = false;
    Serial.println(F("Attract mode resumed"));
    return;
  }

  // Normal MPF update
  if (p[0]=='N' || p[0]=='n'){
    if (!parseNLine(p)) Serial.println(F("ERR parse N line"));
    return;
  }
}

void setup(){
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_OUT_EN, OUTPUT);
  setBrightness(ATTRACT_DIM);

  Serial.begin(BAUD);
  delay(250);

  randomSeed(analogRead(A0)^micros());

  // Attract: random digits (red)
  for (uint8_t i=0;i<NUM_TUBES;i++)
    setTube(i, random(0,10), 255, 0, 0, true, false, ATTRACT_DIM);

  render(); render();             // prime chain
  lastAttract = millis();
}

void loop(){
  // Serial reader
  while (Serial.available()){
    char c=(char)Serial.read();
    lastByteAt = millis();
    if (c=='\n' || c=='\r'){
      if (blen){ buf[blen]=0; handleLine(buf); blen=0; }
    } else if (blen+1 < sizeof(buf)){
      buf[blen++] = c;
    } else {
      blen = 0; Serial.println(F("ERR buffer overflow"));
    }
  }
  if (blen>0 && (millis()-lastByteAt)>=IDLE_PARSE_MS){
    buf[blen]=0; handleLine(buf); blen=0;
  }

  // Attract until first valid command
  if (!gotFirstCommand){
    unsigned long now = millis();
    if (now - lastAttract >= ATTRACT_MS){
      setBrightness(ATTRACT_DIM);
      for (uint8_t i=0;i<NUM_TUBES;i++)
        setTube(i, random(0,10), 255, 0, 0, true, false, ATTRACT_DIM);
      render();
      lastAttract = now;
    }
  }
}
