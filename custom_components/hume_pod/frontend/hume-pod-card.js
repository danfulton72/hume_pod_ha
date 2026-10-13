/**
 * Hume Body Pod card for Home Assistant.
 *
 * Overview, segmental body map and trend charts for each person on a Body Pod,
 * modelled on the Blue2Scale web dashboard by Jozef Jarosciak
 * (https://github.com/JozefJarosciak/Blue2Scale.com), including its body
 * silhouettes, segment colouring and metric groupings.
 *
 * Data comes from the integration's `hume_pod/subscribe` websocket feed
 * (latest results) and the recorder's long-term statistics (trends).
 */

const CARD_VERSION = "0.3.3";

const COLORS = {
  blue: "#3b82f6", amber: "#f59e0b", green: "#22c55e", cyan: "#06b6d4",
  purple: "#8b5cf6", pink: "#ec4899", teal: "#14b8a6", red: "#ef4444",
};
const GRADIENTS = {
  blue: "linear-gradient(135deg,#3b82f6,#1d4ed8)",
  amber: "linear-gradient(135deg,#f59e0b,#d97706)",
  green: "linear-gradient(135deg,#22c55e,#16a34a)",
  cyan: "linear-gradient(135deg,#06b6d4,#0891b2)",
};

// Keys reported in kilograms (converted for imperial users).
const MASS_KEYS = new Set([
  "weight", "fat_mass", "subcutaneous_fat_mass", "android_fat", "gynoid_fat", "lean_mass",
  "skeletal_muscle_mass", "body_cell_mass", "total_body_water", "extracellular_water",
  "intracellular_water", "bone_mineral", "mineral_mass", "skeletal_mass", "organ_mass",
  "right_arm_muscle", "left_arm_muscle", "trunk_muscle", "right_leg_muscle", "left_leg_muscle",
  "right_arm_fat_mass", "left_arm_fat_mass", "trunk_fat_mass", "right_leg_fat_mass", "left_leg_fat_mass",
]);

const METRIC_LABELS = {
  weight: "Weight", bmi: "BMI", body_fat: "Body fat", fat_mass: "Fat mass",
  subcutaneous_fat_mass: "Subcutaneous fat", subcutaneous_fat: "Subcutaneous fat %",
  visceral_fat: "Visceral fat", android_fat: "Android fat", gynoid_fat: "Gynoid fat",
  android_gynoid_ratio: "A/G ratio", lean_mass: "Lean mass", lean_mass_percentage: "Lean mass %",
  skeletal_muscle_mass: "Skeletal muscle", body_cell_mass: "Body cell mass", body_water: "Body water",
  total_body_water: "Total water", extracellular_water: "ECW", intracellular_water: "ICW",
  bone_mineral: "Bone mineral", mineral_mass: "Mineral mass", skeletal_mass: "Skeletal mass",
  organ_mass: "Organ mass", bmr: "BMR", metabolic_age: "Metabolic age",
};
const PCT_KEYS = new Set(["body_fat", "subcutaneous_fat", "android_gynoid_ratio", "lean_mass_percentage", "body_water"]);
const OTHER_UNITS = { bmr: "kcal", metabolic_age: "yrs" };

const RANGES = { "1W": 7, "1M": 30, "3M": 90, "6M": 182, "1Y": 365, ALL: null };

const CHARTS = [
  { id: "weight", title: "Weight", color: COLORS.blue, series: [["weight", COLORS.blue]] },
  { id: "fat", title: "Body fat", color: COLORS.amber, series: [["body_fat", COLORS.amber]] },
  { id: "muscle", title: "Muscle & lean mass", color: COLORS.green,
    series: [["skeletal_muscle_mass", COLORS.green], ["lean_mass", "#16a34a", true]] },
  { id: "composition", title: "Lean vs fat mass", color: COLORS.purple,
    series: [["lean_mass", COLORS.blue], ["fat_mass", COLORS.amber]] },
  { id: "hydration", title: "Body water", color: COLORS.cyan, series: [["body_water", COLORS.cyan]] },
  { id: "bmi", title: "BMI", color: COLORS.pink, series: [["bmi", COLORS.pink]] },
  { id: "metabolic", title: "Metabolic age", color: COLORS.purple, series: [["metabolic_age", COLORS.purple]] },
];

const REASONS = {
  no_match: "nobody's recent weight is close enough",
  ambiguous: "two people are too close to call",
  no_people: "no people are set up on this scale",
};

// ---------------------------------------------------------------------------
// Body map (silhouettes, regions, label positions and ratings from Blue2Scale)
// ---------------------------------------------------------------------------

const MALE_PATH = "M3800 19281 c-106 -12 -186 -44 -275 -111 -46 -34 -57 -38 -132 -42 -61 -3 -94 -11 -138 -32 -154 -76 -278 -267 -346 -536 -22 -85 -24 -116 -24 -300 1 -195 2 -211 33 -339 l32 -134 -24 -28 c-51 -60 -56 -190 -16 -366 25 -105 55 -168 103 -215 38 -36 45 -40 98 -52 21 -5 30 -17 49 -68 34 -94 76 -174 115 -217 30 -33 35 -45 35 -89 0 -136 -58 -301 -147 -413 -50 -64 -155 -154 -252 -216 -144 -93 -342 -168 -756 -288 -304 -88 -472 -192 -593 -368 -136 -197 -195 -397 -227 -762 -19 -221 -26 -266 -74 -469 -71 -298 -101 -500 -101 -686 0 -323 -40 -590 -144 -960 -135 -480 -148 -538 -166 -695 -29 -273 -31 -404 -16 -964 17 -582 36 -918 63 -1111 13 -92 15 -162 9 -355 -8 -319 6 -398 96 -550 23 -38 66 -117 95 -175 73 -142 101 -169 258 -245 185 -91 330 -135 458 -138 58 -2 71 1 83 17 23 33 16 58 -40 146 -95 150 -144 190 -286 232 -56 16 -63 34 -86 230 -18 162 -12 207 32 226 14 7 29 10 33 7 5 -2 19 -33 31 -67 30 -80 90 -185 127 -219 73 -69 147 -87 196 -49 51 40 42 121 -28 250 -87 161 -104 205 -123 315 -29 163 -46 196 -187 360 -43 50 -90 115 -104 145 -24 51 -26 64 -24 180 2 210 60 572 215 1335 28 138 54 269 59 293 5 23 20 119 34 213 17 118 41 227 79 357 30 103 73 257 95 342 22 85 68 258 101 384 33 125 83 331 112 457 37 161 55 223 60 207 4 -13 20 -129 37 -258 16 -129 34 -269 40 -310 5 -41 24 -172 43 -290 33 -215 33 -215 33 -580 -1 -443 -4 -478 -110 -1095 -76 -445 -131 -867 -162 -1225 -27 -323 -25 -1065 4 -1435 12 -154 29 -390 38 -525 9 -135 25 -333 36 -440 10 -107 23 -244 29 -305 6 -60 24 -225 41 -365 28 -226 31 -272 25 -405 -4 -82 -11 -283 -15 -445 -7 -266 -11 -311 -39 -460 -82 -442 -97 -610 -97 -1065 0 -437 5 -484 124 -1250 33 -208 50 -352 81 -670 11 -115 32 -311 46 -435 34 -294 27 -391 -38 -568 -28 -75 -30 -89 -24 -155 15 -149 26 -127 -241 -489 -132 -178 -153 -220 -153 -305 0 -46 4 -58 27 -79 22 -21 35 -25 62 -20 25 4 41 0 59 -14 28 -22 91 -26 140 -9 25 8 35 7 57 -7 21 -14 38 -15 98 -10 80 8 93 8 191 0 59 -5 72 -3 97 15 l28 21 35 -21 c32 -18 48 -20 158 -17 142 4 189 20 223 78 17 30 20 51 19 150 -1 97 -5 126 -28 189 -25 71 -26 83 -26 278 0 199 1 205 31 299 34 107 34 128 -7 247 -23 66 -24 84 -24 306 0 130 5 288 11 351 15 161 117 766 174 1035 43 202 79 396 102 550 23 155 23 610 -1 894 -31 371 -21 503 60 782 122 425 140 542 159 1064 14 408 13 398 110 935 15 80 42 231 61 335 35 193 133 762 135 780 2 21 20 -53 34 -140 8 -49 26 -153 40 -230 14 -77 41 -232 60 -345 20 -113 51 -286 70 -385 88 -466 115 -683 115 -944 1 -441 34 -667 158 -1071 27 -91 56 -203 62 -249 15 -97 9 -380 -14 -731 -31 -456 -20 -581 95 -1165 47 -234 123 -658 169 -945 28 -168 43 -418 38 -609 -4 -128 -9 -167 -27 -216 -36 -99 -37 -158 -5 -245 25 -70 27 -88 31 -276 5 -198 4 -203 -23 -285 -23 -73 -27 -101 -28 -214 -1 -110 2 -134 17 -157 33 -47 79 -61 220 -66 119 -4 131 -3 158 17 l28 21 33 -20 c40 -24 144 -28 173 -6 17 12 25 12 54 0 43 -18 128 -18 164 1 20 10 35 12 53 5 40 -15 120 -12 134 5 8 9 30 15 59 15 126 0 133 143 14 306 -303 420 -318 443 -316 504 1 19 4 62 8 96 6 54 4 69 -25 140 -17 43 -38 106 -46 139 -16 70 -19 297 -4 395 5 36 26 220 45 410 51 495 61 576 106 855 95 595 114 784 113 1130 -1 327 -33 710 -79 945 -8 41 -25 125 -37 185 -18 90 -23 163 -29 405 -4 162 -11 360 -14 440 -6 117 -3 176 13 305 11 88 26 207 32 265 6 58 18 161 26 230 26 230 43 414 54 585 6 94 20 292 30 440 35 493 45 707 43 997 -3 470 -35 868 -118 1443 -47 321 -57 384 -99 620 -52 298 -75 526 -83 846 -6 267 -2 328 48 683 16 115 47 348 69 518 21 171 41 312 43 315 3 2 11 -22 17 -54 9 -44 113 -470 194 -793 24 -97 112 -409 130 -464 60 -180 85 -291 116 -516 6 -47 44 -251 85 -455 85 -423 138 -718 197 -1085 7 -41 12 -145 12 -230 1 -181 -3 -193 -108 -313 -130 -150 -181 -239 -196 -349 -17 -115 -45 -196 -105 -296 -66 -112 -101 -206 -91 -246 12 -47 49 -76 98 -76 92 0 181 90 242 244 53 132 57 136 101 91 30 -30 32 -74 10 -255 -20 -155 -32 -178 -102 -196 -98 -25 -174 -78 -208 -145 -10 -19 -38 -58 -62 -87 -24 -30 -46 -65 -49 -78 -8 -33 18 -71 55 -79 79 -17 337 53 501 135 165 83 189 107 255 250 17 36 56 109 88 162 100 168 101 176 98 508 -2 242 1 308 18 435 39 284 64 851 65 1470 1 386 -1 433 -22 585 -28 202 -59 338 -145 630 -120 411 -141 533 -157 925 -13 322 -46 571 -100 756 -39 131 -69 307 -79 469 -26 390 -99 631 -250 822 -142 180 -305 264 -751 388 -332 93 -534 188 -711 337 -154 129 -219 243 -249 433 -10 63 -15 121 -12 130 3 8 19 31 35 50 33 37 110 195 121 246 6 25 14 32 52 42 62 17 134 90 162 164 26 69 52 225 52 310 0 79 -13 124 -45 158 l-25 26 19 69 c51 184 66 453 36 647 -18 124 -78 303 -135 403 -68 121 -172 219 -302 284 -57 28 -137 60 -178 70 -85 21 -283 32 -380 22z";
const FEMALE_PATH = "M3025 18650 c-294 -46 -605 -444 -694 -890 -29 -150 -39 -235 -56 -495 -17 -265 -26 -343 -55 -475 -11 -52 -32 -147 -45 -210 -73 -334 -46 -693 72 -958 17 -39 20 -54 11 -57 -7 -3 -94 -31 -193 -64 -322 -104 -442 -165 -576 -289 -151 -141 -253 -336 -332 -642 -76 -291 -130 -759 -142 -1225 -3 -137 -13 -340 -20 -450 -8 -110 -19 -273 -25 -362 -12 -188 -31 -306 -66 -418 -134 -424 -220 -1203 -239 -2160 -9 -481 -33 -748 -91 -1005 -9 -41 -17 -118 -17 -170 0 -86 3 -104 38 -195 20 -55 47 -138 60 -185 28 -110 41 -133 112 -201 129 -125 417 -279 521 -279 61 0 78 59 41 140 -11 25 -30 69 -41 98 -25 67 -61 100 -172 159 -48 26 -94 56 -102 67 -7 12 -21 90 -30 175 l-17 154 29 23 c28 23 81 41 91 31 5 -6 38 -136 68 -272 23 -103 46 -149 84 -164 36 -15 60 -9 91 24 43 45 43 78 6 532 -24 286 -27 297 -141 523 -93 183 -95 191 -95 347 0 182 18 293 105 642 41 163 106 431 145 596 39 165 89 374 111 465 126 516 272 1226 365 1762 10 59 20 105 22 103 2 -2 15 -34 28 -71 12 -36 50 -107 83 -158 33 -50 64 -103 70 -117 16 -44 49 -306 56 -444 3 -71 5 -213 5 -315 0 -155 -4 -203 -24 -295 -26 -119 -31 -138 -131 -450 -275 -863 -342 -1121 -390 -1515 -46 -385 -35 -1015 31 -1680 52 -532 94 -838 204 -1505 49 -298 60 -385 71 -567 19 -318 1 -751 -42 -1008 -6 -36 -31 -155 -55 -265 -74 -341 -78 -371 -77 -580 1 -264 23 -413 158 -1042 36 -165 83 -390 105 -500 21 -109 63 -310 91 -448 49 -234 52 -260 53 -400 1 -150 1 -150 -37 -250 -33 -88 -37 -109 -35 -181 2 -99 -3 -108 -163 -324 -153 -206 -177 -242 -194 -291 -20 -55 -19 -119 2 -149 23 -34 33 -40 73 -40 19 0 44 -7 54 -15 24 -18 71 -19 115 -4 23 8 39 8 54 1 41 -20 87 -22 134 -6 35 12 52 13 70 5 39 -18 114 -13 151 9 l33 20 28 -21 c26 -19 39 -21 134 -17 100 3 108 5 144 34 49 39 72 104 73 204 0 77 -5 105 -41 222 -19 59 -21 85 -17 220 4 113 9 163 21 190 24 52 21 124 -7 209 -30 88 -46 270 -50 543 -4 340 22 655 74 881 37 161 130 633 141 720 9 62 11 199 8 435 -2 190 -3 453 -3 585 1 324 4 339 149 815 85 277 99 389 115 900 6 207 19 412 35 565 111 1058 119 1160 119 1522 1 295 1 302 21 307 11 3 30 3 42 0 20 -6 21 -12 26 -322 4 -207 13 -385 26 -512 39 -382 71 -668 100 -915 21 -173 34 -336 41 -530 24 -694 25 -698 164 -1161 106 -356 112 -398 106 -779 -9 -556 -5 -828 14 -955 17 -114 57 -320 116 -600 17 -80 42 -224 57 -320 25 -163 27 -199 27 -520 1 -375 -12 -561 -45 -654 -32 -91 -34 -133 -10 -210 29 -95 31 -348 2 -434 -28 -85 -33 -116 -33 -203 1 -93 15 -149 45 -185 43 -50 240 -73 303 -35 29 18 31 18 65 0 37 -20 119 -25 149 -9 13 7 36 6 77 -5 52 -14 63 -14 109 1 39 12 57 13 72 5 29 -16 85 -14 108 4 10 8 38 15 62 15 67 0 85 25 80 114 -4 93 -32 149 -145 293 -104 132 -184 245 -208 292 -14 28 -16 49 -11 110 7 72 5 82 -29 171 -58 149 -63 279 -20 510 28 146 122 607 215 1045 123 581 137 660 155 835 28 279 17 439 -51 768 -103 496 -116 617 -117 1047 0 327 11 463 63 775 119 717 141 872 205 1445 58 516 92 1215 75 1503 -35 565 -123 948 -430 1872 -154 464 -155 471 -153 755 3 384 27 639 70 740 9 22 36 67 59 100 35 50 66 115 103 219 4 11 20 -59 39 -170 62 -361 171 -912 238 -1204 24 -107 63 -276 86 -375 52 -231 213 -889 271 -1115 90 -346 117 -504 117 -696 0 -161 -9 -193 -106 -386 -40 -81 -83 -180 -94 -219 -24 -89 -55 -441 -55 -636 0 -139 1 -143 25 -167 14 -14 37 -28 53 -31 23 -6 33 -1 66 31 40 41 39 36 82 244 37 177 36 173 74 167 60 -10 85 -34 85 -81 0 -50 -27 -276 -35 -296 -3 -8 -52 -41 -110 -74 -57 -32 -113 -68 -124 -80 -25 -26 -111 -223 -111 -253 0 -26 44 -63 76 -63 87 0 388 165 506 278 76 72 92 100 118 202 12 47 37 128 56 180 51 135 53 189 16 395 -61 336 -69 430 -82 986 -16 660 -46 1077 -105 1459 -8 52 -22 140 -30 196 -23 155 -73 386 -111 514 -25 84 -38 155 -49 265 -8 83 -19 191 -25 240 -5 50 -14 227 -20 395 -26 760 -71 1217 -150 1533 -23 90 -94 305 -118 352 -58 118 -158 253 -235 319 -117 99 -301 192 -477 241 -82 23 -249 81 -258 90 -2 2 13 54 32 116 46 149 69 324 69 519 0 181 -12 270 -60 475 -49 211 -87 414 -111 600 -12 88 -33 246 -47 350 -33 256 -58 358 -125 514 -150 350 -403 538 -695 516 -114 -8 -158 -9 -270 -2 -49 3 -117 2 -150 -3z";

const SEGMENT_REGIONS = {
  male: {
    right_arm: { x: 0, y: 280, w: 230, h: 700 }, left_arm: { x: 520, y: 280, w: 230, h: 700 },
    trunk: { x: 230, y: 200, w: 290, h: 660 },
    right_leg: { x: 210, y: 870, w: 170, h: 1130 }, left_leg: { x: 380, y: 870, w: 170, h: 1130 },
  },
  female: {
    right_arm: { x: 0, y: 300, w: 190, h: 650 }, left_arm: { x: 450, y: 300, w: 190, h: 650 },
    trunk: { x: 190, y: 200, w: 260, h: 640 },
    right_leg: { x: 155, y: 850, w: 170, h: 1100 }, left_leg: { x: 315, y: 850, w: 170, h: 1100 },
  },
};
const LABEL_POSITIONS = {
  male: {
    right_arm: { x: 120, y: 480 }, left_arm: { x: 630, y: 480 }, trunk: { x: 375, y: 600 },
    right_leg: { x: 280, y: 1300 }, left_leg: { x: 470, y: 1300 },
  },
  female: {
    right_arm: { x: 90, y: 480 }, left_arm: { x: 550, y: 480 }, trunk: { x: 320, y: 580 },
    right_leg: { x: 230, y: 1280 }, left_leg: { x: 410, y: 1280 },
  },
};
const SEGMENTS = [
  ["right_arm", "Right arm"], ["left_arm", "Left arm"], ["trunk", "Trunk"],
  ["right_leg", "Right leg"], ["left_leg", "Left leg"],
];
const SEG_RATING = {
  fat_pct: (v) => (v < 18 ? ["Low", "#60a5fa"] : v < 25 ? ["Normal", "#4ade80"] : v < 32 ? ["High", "#fbbf24"] : ["Very high", "#f87171"]),
  fat_kg: (v) => (v < 1.5 ? ["Low", "#4ade80"] : v < 3 ? ["Normal", "#60a5fa"] : v < 5 ? ["High", "#fbbf24"] : ["Very high", "#f87171"]),
  muscle_kg: (v) => (v > 8 ? ["High", "#4ade80"] : v > 4 ? ["Normal", "#60a5fa"] : v > 2 ? ["Low", "#fbbf24"] : ["Very low", "#f87171"]),
};
const SEG_LEGEND = {
  fat_pct: [["Low (<18%)", "#60a5fa"], ["Normal (18–25%)", "#4ade80"], ["High (25–32%)", "#fbbf24"], ["Very high (>32%)", "#f87171"]],
  fat_kg: [["Low", "#4ade80"], ["Normal", "#60a5fa"], ["High", "#fbbf24"], ["Very high", "#f87171"]],
  muscle_kg: [["Very low", "#f87171"], ["Low", "#fbbf24"], ["Normal", "#60a5fa"], ["High", "#4ade80"]],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const KG_TO_LB = 2.2046226218;

function storageGet(key) {
  try { return window.localStorage.getItem(key); } catch (_e) { return null; }
}
function storageSet(key, value) {
  try { window.localStorage.setItem(key, value); } catch (_e) { /* private mode etc. */ }
}

class HumePodCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("hume-pod-card-editor");
  }

  static getStubConfig() {
    return { view: "overview" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._snapshot = null;
    this._tab = null;
    this._personId = null;
    this._segView = "muscle_kg";
    this._range = storageGet("hume-pod-card:range") || "3M";
    this._stats = {}; // cacheKey -> {statistic_id: [[t, v], ...]} | "loading" | "error"
    this._customMetric = "weight";
    this._charts = new Map();
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    this.shadowRoot.addEventListener("pointermove", (ev) => this._onHover(ev));
    this.shadowRoot.addEventListener("pointerleave", (ev) => this._onHover(ev), true);
  }

  setConfig(config) {
    this._config = { view: "overview", show_tabs: true, ...config };
    this._tab = this._config.view;
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || !this._unsub) this._subscribe();
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  getCardSize() {
    return 10;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  // ---- data ---------------------------------------------------------------

  _subscribe() {
    if (!this._hass?.connection || this._unsub) return;
    this._unsub = this._hass.connection
      .subscribeMessage((snapshot) => {
        this._snapshot = snapshot;
        this._render();
      }, { type: "hume_pod/subscribe" })
      .catch((err) => {
        this._error = err?.message || String(err);
        this._unsub = null;
        this._render();
      });
  }

  get _imperial() {
    return this._hass?.config?.unit_system?.mass === "lb";
  }

  get _massUnit() {
    return this._imperial ? "lb" : "kg";
  }

  _unit(key) {
    if (MASS_KEYS.has(key)) return this._massUnit;
    if (PCT_KEYS.has(key)) return "%";
    return OTHER_UNITS[key] || "";
  }

  _conv(key, value) {
    if (value === null || value === undefined || Number.isNaN(value)) return null;
    return MASS_KEYS.has(key) && this._imperial ? value * KG_TO_LB : value;
  }

  _fmt(value, decimals = 1) {
    if (value === null || value === undefined || Number.isNaN(value)) return "—";
    const lang = this._hass?.locale?.language || navigator.language;
    return new Intl.NumberFormat(lang, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
  }

  _decimals(key) {
    if (key === "weight") return this._imperial ? 1 : 2;
    if (["visceral_fat", "bmr", "metabolic_age"].includes(key)) return 0;
    return 1;
  }

  _val(person, key) {
    return this._conv(key, person?.data?.[key]);
  }

  _fmtDate(iso, withTime = true) {
    if (!iso) return "—";
    const lang = this._hass?.locale?.language || navigator.language;
    const opts = withTime
      ? { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }
      : { day: "numeric", month: "short", year: "numeric" };
    return new Intl.DateTimeFormat(lang, opts).format(new Date(iso));
  }

  _people() {
    const out = [];
    for (const scale of this._snapshot?.scales || []) {
      for (const p of scale.people) out.push({ ...p, scale });
    }
    return out;
  }

  _selectedPerson(people) {
    const cfg = this._config?.person;
    if (cfg) {
      const fixed = people.find((p) => p.device_id === cfg || p.person_id === cfg
        || p.name.toLowerCase() === String(cfg).toLowerCase());
      if (fixed) return fixed;
    }
    const remembered = this._personId || storageGet("hume-pod-card:person");
    return people.find((p) => p.person_id === remembered) || people[0];
  }

  async _ensureStats(person, rangeKey) {
    const ids = [...new Set(Object.values(person.entities || {}))];
    const cacheKey = `${person.person_id}|${rangeKey}|${this._massUnit}`;
    const cached = this._stats[cacheKey];
    if (cached && (cached === "loading" || Date.now() - cached.fetched < 5 * 60 * 1000)) return;
    if (!ids.length) {
      this._stats[cacheKey] = { fetched: Date.now(), series: {} };
      return;
    }
    this._stats[cacheKey] = "loading";

    const days = RANGES[rangeKey];
    const end = new Date();
    const start = days ? new Date(end.getTime() - days * 86400000) : new Date("2015-01-01T00:00:00Z");
    const period = !days || days > 365 ? "month" : days > 90 ? "week" : "day";
    try {
      const res = await this._hass.callWS({
        type: "recorder/statistics_during_period",
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        statistic_ids: ids,
        period,
        types: ["mean"],
        units: { mass: this._massUnit },
      });
      const series = {};
      for (const [id, rows] of Object.entries(res || {})) {
        series[id] = rows
          .filter((r) => r.mean !== null && r.mean !== undefined)
          .map((r) => [typeof r.start === "number" ? r.start : Date.parse(r.start), r.mean]);
      }
      this._stats[cacheKey] = { fetched: Date.now(), series };
    } catch (err) {
      this._stats[cacheKey] = { fetched: Date.now(), series: {}, error: err?.message || String(err) };
    }
    this._render();
  }

  _seriesFor(person, key, rangeKey) {
    const entity = person.entities?.[key];
    const cached = this._stats[`${person.person_id}|${rangeKey}|${this._massUnit}`];
    if (!entity || !cached || cached === "loading") return null;
    return cached.series[entity] || [];
  }

  // ---- events -------------------------------------------------------------

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n.dataset && Object.keys(n.dataset).length);
    if (!el) return;
    const d = el.dataset;
    if (d.tab) {
      this._tab = d.tab;
    } else if (d.person) {
      this._personId = d.person;
      storageSet("hume-pod-card:person", d.person);
    } else if (d.range) {
      this._range = d.range;
      storageSet("hume-pod-card:range", d.range);
    } else if (d.seg) {
      this._segView = d.seg;
    } else if (d.assign) {
      this._hass.callService("hume_pod", "assign_weigh_in", { person: d.assign });
      return;
    } else if (d.discard) {
      this._hass.callService("hume_pod", "discard_weigh_in", { scale: d.discard });
      return;
    } else if (d.more) {
      const event = new Event("hass-more-info", { bubbles: true, composed: true });
      event.detail = { entityId: d.more };
      this.dispatchEvent(event);
      return;
    } else {
      return;
    }
    this._render();
  }

  _onChange(ev) {
    if (ev.target?.dataset?.custom !== undefined) {
      this._customMetric = ev.target.value;
      this._render();
    }
  }

  _onHover(ev) {
    const svg = ev.composedPath().find((n) => n.tagName === "svg" && n.dataset?.chart);
    for (const [id, chart] of this._charts) {
      const tip = this.shadowRoot.getElementById(`tip-${id}`);
      const cross = this.shadowRoot.getElementById(`cross-${id}`);
      if (!tip || !cross) continue;
      if (!svg || svg.dataset.chart !== id || ev.type === "pointerleave") {
        tip.style.display = "none";
        cross.setAttribute("visibility", "hidden");
        continue;
      }
      const rect = svg.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * chart.w;
      const t = chart.xToT(x);
      const lines = [];
      let px = null;
      for (const s of chart.series) {
        if (!s.points.length) continue;
        let best = s.points[0];
        for (const p of s.points) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
        px = px ?? chart.tToX(best[0]);
        lines.push(`<div><span class="dot" style="background:${s.color}"></span>${esc(s.name)}: <b>${this._fmt(best[1], s.decimals)}</b> ${esc(s.unit)}</div>`);
        if (lines.length === 1) lines.unshift(`<div class="tip-date">${this._fmtDate(new Date(best[0]).toISOString(), false)}</div>`);
      }
      if (px === null) continue;
      cross.setAttribute("x1", px);
      cross.setAttribute("x2", px);
      cross.setAttribute("visibility", "visible");
      tip.innerHTML = lines.join("");
      tip.style.display = "block";
      const left = (px / chart.w) * rect.width;
      tip.style.left = `${Math.min(Math.max(left, 60), rect.width - 60)}px`;
    }
  }

  // ---- rendering ----------------------------------------------------------

  _render() {
    if (!this.shadowRoot || !this._config) return;
    this._charts.clear();
    const people = this._people();
    let body;
    if (this._error) {
      body = `<div class="empty">Couldn't load Body Pod data: ${esc(this._error)}</div>`;
    } else if (!this._snapshot) {
      body = `<div class="empty"><ha-circular-progress indeterminate size="small"></ha-circular-progress></div>`;
    } else if (!people.length) {
      body = `<div class="empty"><ha-icon icon="mdi:scale-bathroom"></ha-icon>
        <p><b>No people yet</b></p><p>Add the Hume Body Pod integration and a person to start tracking.</p></div>`;
    } else {
      const person = this._selectedPerson(people);
      this._personId = person.person_id;
      body = this._renderPerson(person, people);
    }
    const title = this._config.title ? `<h1 class="title">${esc(this._config.title)}</h1>` : "";
    this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card>${title}<div class="root">${body}</div></ha-card>`;
  }

  _renderPerson(person, people) {
    const fixed = Boolean(this._config.person);
    const tabs = [["overview", "mdi:view-dashboard-outline", "Overview"], ["body", "mdi:human", "Body map"], ["trends", "mdi:chart-line", "Trends"]];
    const tab = tabs.some(([t]) => t === this._tab) ? this._tab : "overview";
    if (tab === "trends" || tab === "overview") this._ensureStats(person, tab === "trends" ? this._range : "1M");

    const chips = !fixed && people.length > 1
      ? `<div class="chips">${people.map((p) => `<button class="chip ${p.person_id === person.person_id ? "active" : ""}" data-person="${esc(p.person_id)}"><ha-icon icon="mdi:account"></ha-icon>${esc(p.name)}</button>`).join("")}</div>`
      : `<div class="who"><ha-icon icon="mdi:account"></ha-icon>${esc(person.name)}</div>`;
    const tabBar = this._config.show_tabs === false ? "" : `<div class="tabs">${tabs.map(([t, icon, label]) => `<button class="tab ${t === tab ? "active" : ""}" data-tab="${t}"><ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`).join("")}</div>`;

    let content;
    if (!person.measured_at) {
      content = `<div class="empty"><ha-icon icon="mdi:scale-bathroom"></ha-icon><p><b>No measurements yet</b></p>
        <p>Tap the Body Pod to wake it and step on barefoot. ${esc(person.name)}'s results will appear here.</p></div>`;
    } else if (tab === "body") {
      content = this._renderBodyMap(person);
    } else if (tab === "trends") {
      content = this._renderTrends(person);
    } else {
      content = this._renderOverview(person);
    }

    return `<div class="head">${chips}${tabBar}</div>${this._renderBanners(person, people)}${content}`;
  }

  _renderBanners(person, people) {
    const scale = person.scale;
    let out = "";
    if (scale.status === "measuring" && scale.live_weight) {
      out += `<div class="banner live"><ha-icon icon="mdi:scale-bathroom"></ha-icon>
        <span>Measuring… <b>${this._fmt(this._conv("weight", scale.live_weight), this._decimals("weight"))} ${this._massUnit}</b>. Stay still, barefoot on all four pads.</span></div>`;
    }
    if (scale.pending) {
      const p = scale.pending;
      const onScale = people.filter((x) => x.scale.entry_id === scale.entry_id && x.device_id);
      out += `<div class="banner pending"><ha-icon icon="mdi:account-question"></ha-icon>
        <div class="banner-text">Unassigned weigh-in: <b>${this._fmt(this._conv("weight", p.weight), this._decimals("weight"))} ${this._massUnit}</b>
        at ${this._fmtDate(p.measured_at)} (${esc(REASONS[p.reason] || p.reason)}).</div>
        <div class="banner-actions">${onScale.map((x) => `<button class="btn" data-assign="${esc(x.device_id)}">${esc(x.name)}</button>`).join("")}
        ${scale.device_id ? `<button class="btn ghost" data-discard="${esc(scale.device_id)}">Discard</button>` : ""}</div></div>`;
    }
    return out;
  }

  _statCard(person, key, title, icon, gradient) {
    const value = this._val(person, key);
    const unit = this._unit(key);
    const series = this._seriesFor(person, key, "1M");
    let trend = "";
    let spark = "";
    if (series && series.length > 1) {
      const first = series[0][1];
      const last = value ?? series[series.length - 1][1];
      const diff = last - first;
      const sign = diff > 0 ? "+" : diff < 0 ? "−" : "±";
      trend = `<div class="trend"><ha-icon icon="${diff >= 0 ? "mdi:trending-up" : "mdi:trending-down"}"></ha-icon>${sign}${this._fmt(Math.abs(diff), 1)} ${unit} in 30 days</div>`;
      const vals = series.slice(-7).map((p) => p[1]);
      const min = Math.min(...vals);
      const range = Math.max(...vals) - min || 1;
      spark = `<div class="spark">${vals.map((v) => `<i style="height:${Math.max(15, ((v - min) / range) * 100)}%" title="${this._fmt(v, 1)} ${esc(unit)}"></i>`).join("")}</div>`;
    }
    const entity = person.entities?.[key];
    return `<div class="stat" style="background:${GRADIENTS[gradient]}" ${entity ? `data-more="${esc(entity)}"` : ""}>
      <ha-icon class="bg-icon" icon="${icon}"></ha-icon>
      <div class="stat-title">${title}</div>
      <div class="stat-value"><span>${this._fmt(value, this._decimals(key))}</span><small>${unit}</small></div>
      ${trend}${spark}</div>`;
  }

  _row(person, key, label, icon, color) {
    const entity = person.entities?.[key];
    return `<div class="row" ${entity ? `data-more="${esc(entity)}"` : ""}>
      <span class="row-label">${icon ? `<ha-icon icon="${icon}" style="color:${color}"></ha-icon>` : ""}${label}</span>
      <span class="row-value">${this._fmt(this._val(person, key), this._decimals(key))}<small>${this._unit(key)}</small></span></div>`;
  }

  _renderOverview(person) {
    const d = person.data;
    const hasComp = d.lean_mass !== undefined;
    const stats = `<div class="stats">
      ${this._statCard(person, "weight", "Weight", "mdi:scale-bathroom", "blue")}
      ${this._statCard(person, "body_fat", "Body fat", "mdi:water-percent", "amber")}
      ${this._statCard(person, "skeletal_muscle_mass", "Muscle mass", "mdi:arm-flex", "green")}
      ${this._statCard(person, "body_water", "Body water", "mdi:water", "cyan")}</div>`;
    if (!hasComp) {
      return `${stats}<div class="note">Body composition appears after a barefoot weigh-in with feet on all four pads.</div>${this._summary(person)}`;
    }

    // Donut: fat + lean + bone/mineral = total weight
    const fat = this._val(person, "fat_mass") || 0;
    const lean = this._val(person, "lean_mass") || 0;
    const bone = (this._val(person, "bone_mineral") || 0) + (this._val(person, "mineral_mass") || 0);
    const total = fat + lean + bone || 1;
    const parts = [[lean, COLORS.blue], [fat, COLORS.amber], [bone, COLORS.purple]];
    const C = 2 * Math.PI * 40;
    let acc = 0;
    const arcs = parts.map(([v, c]) => {
      const len = (v / total) * C;
      const arc = `<circle cx="50" cy="50" r="40" fill="none" stroke="${c}" stroke-width="14" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-acc}" transform="rotate(-90 50 50)"/>`;
      acc += len;
      return arc;
    }).join("");
    const donut = `<div class="panel accent" style="--accent:${COLORS.blue}">
      <div class="panel-title">Body composition</div>
      <div class="donut-wrap">
        <svg class="donut" viewBox="0 0 100 100" role="img" aria-label="Body composition">${arcs}
          <text x="50" y="48" text-anchor="middle" class="donut-value">${this._fmt(this._val(person, "weight"), this._decimals("weight"))}</text>
          <text x="50" y="60" text-anchor="middle" class="donut-unit">${this._massUnit}</text></svg>
        <div class="legend-list">
          <div class="leg"><span class="dot" style="background:${COLORS.blue}"></span>Lean mass<b>${this._fmt(lean, 1)} ${this._massUnit}</b></div>
          <div class="leg"><span class="dot" style="background:${COLORS.amber}"></span>Fat mass<b>${this._fmt(fat, 1)} ${this._massUnit}</b></div>
          <div class="leg"><span class="dot" style="background:${COLORS.purple}"></span>Bone & minerals<b>${this._fmt(bone, 1)} ${this._massUnit}</b></div>
          <div class="leg sub"><span class="dot" style="background:${COLORS.cyan}"></span>of which water<b>${this._fmt(this._val(person, "total_body_water"), 1)} ${this._massUnit}</b></div>
          <div class="leg total">Lean %<b style="color:${COLORS.blue}">${this._fmt(d.lean_mass_percentage, 0)}%</b></div>
        </div></div></div>`;

    const key = `<div class="panel accent" style="--accent:${COLORS.teal}">
      <div class="panel-title">Key metrics</div>
      ${this._row(person, "bmi", "BMI", "mdi:heart-pulse", COLORS.blue)}
      ${this._row(person, "visceral_fat", "Visceral fat", "mdi:stomach", COLORS.red)}
      ${this._row(person, "bmr", "BMR", "mdi:fire", COLORS.amber)}
      ${this._row(person, "metabolic_age", "Metabolic age", "mdi:lightning-bolt", COLORS.purple)}
      ${this._row(person, "bone_mineral", "Bone mineral", "mdi:bone", COLORS.teal)}</div>`;

    const cat = (title, color, keys) => `<div class="panel accent small" style="--accent:${color}">
      <div class="panel-title caps"><span class="dot" style="background:${color}"></span>${title}</div>
      ${keys.map(([k, l]) => this._row(person, k, l)).join("")}</div>`;
    const cats = `<div class="grid3">
      ${cat("Fat analysis", COLORS.amber, [["body_fat", "Body fat"], ["subcutaneous_fat_mass", "Subcutaneous"], ["visceral_fat", "Visceral fat"], ["android_fat", "Android fat"], ["gynoid_fat", "Gynoid fat"]])}
      ${cat("Lean mass", COLORS.green, [["lean_mass", "Lean mass"], ["lean_mass_percentage", "Lean %"], ["skeletal_muscle_mass", "Muscle"], ["body_cell_mass", "Cell mass"], ["organ_mass", "Organ mass"]])}
      ${cat("Hydration", COLORS.cyan, [["body_water", "Body water"], ["total_body_water", "Total water"], ["extracellular_water", "ECW"], ["intracellular_water", "ICW"]])}</div>`;

    return `${stats}<div class="grid2">${donut}${key}</div>${cats}${this._summary(person)}`;
  }

  _summary(person) {
    const height = person.height
      ? this._imperial
        ? `${Math.floor(person.height / 30.48)}′ ${Math.round((person.height / 2.54) % 12)}″`
        : `${person.height} cm`
      : null;
    return `<div class="summary">
      <span>Last weigh-in <b>${this._fmtDate(person.measured_at)}</b></span>
      <span>Body composition <b>${this._fmtDate(person.composition_at)}</b></span>
      ${height ? `<span>Height <b>${height}</b></span>` : ""}</div>`;
  }

  _renderBodyMap(person) {
    const d = person.data;
    if (d.trunk_muscle === undefined) {
      return `<div class="empty"><ha-icon icon="mdi:human"></ha-icon><p>No segmental data yet. Weigh in barefoot with feet on all four pads to see the body map.</p></div>`;
    }
    const sex = person.sex === "female" ? "female" : "male";
    const mode = this._segView;
    const unit = mode === "fat_pct" ? "%" : this._massUnit;
    const value = (seg) => {
      const key = mode === "muscle_kg" ? `${seg}_muscle` : mode === "fat_pct" ? `${seg}_fat` : `${seg}_fat_mass`;
      return this._conv(key, d[key]) ?? 0;
    };
    // Ratings use the original kg thresholds
    const ratingValue = (seg) => (mode === "fat_pct" ? d[`${seg}_fat`] : mode === "muscle_kg" ? d[`${seg}_muscle`] : d[`${seg}_fat_mass`]) ?? 0;

    const path = sex === "male" ? MALE_PATH : FEMALE_PATH;
    const vbW = sex === "male" ? 751 : 641;
    const regions = SEGMENT_REGIONS[sex];
    const labels = LABEL_POSITIONS[sex];
    const t = regions.trunk;
    const rl = regions.right_leg;

    let svg = `<svg class="bodymap" viewBox="0 0 ${vbW} 2000" role="img" aria-label="Segmental body map">
      <defs>
        <clipPath id="bodyClip"><path transform="translate(0,2000) scale(0.1,-0.1)" d="${path}"/></clipPath>
        <filter id="bodyGlow"><feGaussianBlur stdDeviation="8" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <g transform="translate(0,2000) scale(0.1,-0.1)"><path d="${path}" class="body-fill"/></g>
      <g clip-path="url(#bodyClip)">`;
    for (const [seg] of SEGMENTS) {
      const r = regions[seg];
      const [, color] = SEG_RATING[mode](ratingValue(seg));
      svg += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="${color}" fill-opacity="0.45"/>`;
    }
    svg += `<line x1="${t.x}" y1="${t.y}" x2="${t.x}" y2="${t.y + t.h}" class="sep"/>
      <line x1="${t.x + t.w}" y1="${t.y}" x2="${t.x + t.w}" y2="${t.y + t.h}" class="sep"/>
      <line x1="0" y1="${rl.y}" x2="${vbW}" y2="${rl.y}" class="sep"/>
      <line x1="${rl.x + rl.w}" y1="${rl.y}" x2="${rl.x + rl.w}" y2="${rl.y + rl.h}" class="sep"/></g>
      <g transform="translate(0,2000) scale(0.1,-0.1)" filter="url(#bodyGlow)"><path d="${path}" class="body-outline"/></g>`;
    for (const [seg, label] of SEGMENTS) {
      const pos = labels[seg];
      const [, color] = SEG_RATING[mode](ratingValue(seg));
      svg += `<g><rect x="${pos.x - 97.5}" y="${pos.y - 50}" width="195" height="100" rx="16" class="pill" stroke="${color}"/>
        <text x="${pos.x}" y="${pos.y - 12}" text-anchor="middle" class="pill-label">${label}</text>
        <text x="${pos.x}" y="${pos.y + 34}" text-anchor="middle" class="pill-value" fill="${color}">${this._fmt(value(seg), 1)}${unit}</text></g>`;
    }
    svg += "</svg>";

    const top = [
      ["Weight", this._fmt(this._val(person, "weight"), 1), this._massUnit],
      ["Body fat", this._fmt(d.body_fat, 1), "%"],
      ["Lean mass", this._fmt(d.lean_mass_percentage, 1), "%"],
      ["BMI", this._fmt(d.bmi, 1), ""],
    ].map(([l, v, u]) => `<div class="mini"><div class="mini-label">${l}</div><div class="mini-value">${v}<small>${u}</small></div></div>`).join("");

    const legend = SEG_LEGEND[mode].map(([l, c]) => `<span class="leg-item"><span class="dot" style="background:${c}"></span>${l}</span>`).join("");
    const toggle = [["muscle_kg", `Muscle (${this._massUnit})`], ["fat_pct", "Fat (%)"], ["fat_kg", `Fat (${this._massUnit})`]]
      .map(([m, l]) => `<button class="seg-btn ${m === mode ? "active" : ""}" data-seg="${m}">${l}</button>`).join("");

    return `<div class="minis">${top}</div><div class="bodymap-wrap">${svg}</div>
      <div class="seg-legend">${legend}</div><div class="seg-toggle">${toggle}</div>`;
  }

  _renderTrends(person) {
    const ranges = Object.keys(RANGES).map((r) => `<button class="range ${r === this._range ? "active" : ""}" data-range="${r}">${r}</button>`).join("");
    const cached = this._stats[`${person.person_id}|${this._range}|${this._massUnit}`];
    if (!cached || cached === "loading") {
      return `<div class="range-bar">${ranges}</div><div class="empty"><ha-circular-progress indeterminate size="small"></ha-circular-progress></div>`;
    }
    if (cached.error) {
      return `<div class="range-bar">${ranges}</div><div class="empty">Couldn't load history: ${esc(cached.error)}</div>`;
    }

    const charts = CHARTS.map((c) => this._chartPanel(person, c)).join("");
    const options = Object.keys(METRIC_LABELS)
      .filter((k) => person.entities?.[k])
      .map((k) => `<option value="${k}" ${k === this._customMetric ? "selected" : ""}>${METRIC_LABELS[k]}</option>`).join("");
    const custom = this._chartPanel(person, {
      id: "custom", title: "Custom metric", color: COLORS.teal,
      series: [[this._customMetric, COLORS.teal]],
      extra: `<select data-custom>${options}</select>`,
    });
    return `<div class="range-bar">${ranges}</div><div class="charts">${charts}${custom}</div>
      <div class="note">Daily averages from Home Assistant's long-term statistics. Only enabled sensors are charted.</div>`;
  }

  _chartPanel(person, chart) {
    const series = chart.series
      .map(([key, color, dashed]) => ({
        key, color, dashed,
        name: METRIC_LABELS[key] || key,
        unit: this._unit(key),
        decimals: this._decimals(key) === 0 ? 0 : 1,
        points: this._seriesFor(person, key, this._range) || [],
        enabled: Boolean(person.entities?.[key]),
      }))
      .filter((s) => s.enabled);
    const head = `<div class="panel-title">${chart.title}${chart.extra || ""}</div>`;
    if (!series.length) {
      return `<div class="panel accent chart" style="--accent:${chart.color}">${head}<div class="chart-empty">Enable the ${esc(METRIC_LABELS[chart.series[0][0]])} sensor to chart it.</div></div>`;
    }
    const all = series.flatMap((s) => s.points);
    if (all.length < 2) {
      return `<div class="panel accent chart" style="--accent:${chart.color}">${head}<div class="chart-empty">Not enough history yet.</div></div>`;
    }

    const W = 320, H = 150, L = 36, R = 8, T = 10, B = 22;
    const ts = all.map((p) => p[0]);
    const vs = all.map((p) => p[1]);
    const t0 = Math.min(...ts), t1 = Math.max(...ts);
    let v0 = Math.min(...vs), v1 = Math.max(...vs);
    const pad = (v1 - v0) * 0.15 || Math.abs(v1) * 0.02 || 1;
    v0 -= pad; v1 += pad;
    const tToX = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
    const vToY = (v) => T + (1 - (v - v0) / (v1 - v0)) * (H - T - B);
    const xToT = (x) => t0 + ((x - L) / (W - L - R)) * (t1 - t0);
    this._charts.set(chart.id, { w: W, series, tToX, xToT });

    const grid = [0, 0.5, 1].map((f) => {
      const v = v0 + (v1 - v0) * f;
      const y = vToY(v);
      return `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" class="gridline"/><text x="${L - 4}" y="${y + 3}" text-anchor="end" class="axis">${this._fmt(v, Math.abs(v1 - v0) < 10 ? 1 : 0)}</text>`;
    }).join("");
    const lines = series.map((s, i) => {
      if (!s.points.length) return "";
      const d = s.points.map((p, j) => `${j ? "L" : "M"}${tToX(p[0]).toFixed(1)},${vToY(p[1]).toFixed(1)}`).join("");
      const area = series.length === 1
        ? `<path d="${d}L${tToX(s.points[s.points.length - 1][0]).toFixed(1)},${H - B}L${tToX(s.points[0][0]).toFixed(1)},${H - B}Z" fill="url(#grad-${chart.id}-${i})"/>`
        : "";
      return `<defs><linearGradient id="grad-${chart.id}-${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity="0.35"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient></defs>
        ${area}<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" ${s.dashed ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    }).join("");
    const dates = `<text x="${L}" y="${H - 6}" class="axis">${this._fmtDate(new Date(t0).toISOString(), false)}</text>
      <text x="${W - R}" y="${H - 6}" text-anchor="end" class="axis">${this._fmtDate(new Date(t1).toISOString(), false)}</text>`;
    const legend = series.length > 1
      ? `<div class="chart-legend">${series.map((s) => `<span class="leg-item"><span class="dot" style="background:${s.color}"></span>${s.name} (${s.unit})</span>`).join("")}</div>`
      : "";
    const latest = series[0].points[series[0].points.length - 1];
    const latestLabel = series.length === 1 && latest ? `<span class="chart-latest">${this._fmt(latest[1], series[0].decimals)} ${series[0].unit}</span>` : "";

    return `<div class="panel accent chart" style="--accent:${chart.color}">
      <div class="panel-title">${chart.title}${latestLabel}${chart.extra || ""}</div>
      <div class="chart-box"><svg viewBox="0 0 ${W} ${H}" data-chart="${chart.id}" role="img" aria-label="${esc(chart.title)} trend">
        ${grid}${lines}${dates}<line id="cross-${chart.id}" y1="${T}" y2="${H - B}" class="cross" visibility="hidden"/></svg>
        <div class="tip" id="tip-${chart.id}"></div></div>${legend}</div>`;
  }
}

const STYLES = `
  :host { --hp-radius: var(--ha-card-border-radius, 12px); }
  ha-card { display: block; overflow: hidden; }
  .title { margin: 0; padding: 16px 16px 0; font-size: 1.25rem; font-weight: 600; }
  .root { padding: 16px; display: flex; flex-direction: column; gap: 14px; container-type: inline-size; }
  button { font: inherit; cursor: pointer; }
  ha-icon { --mdc-icon-size: 18px; }
  small { font-size: 0.7em; font-weight: 500; opacity: 0.75; margin-left: 3px; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; flex: none; }

  .head { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
  .chips, .tabs { display: flex; gap: 4px; flex-wrap: wrap; }
  .tabs { background: var(--secondary-background-color); border-radius: 999px; padding: 3px; }
  .chip, .tab { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--divider-color); background: none; color: var(--secondary-text-color); border-radius: 999px; padding: 5px 12px; font-size: 0.85rem; }
  .tab { border: none; }
  .chip.active, .tab.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .who { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }
  @container (max-width: 420px) { .tab span { display: none; } }

  .banner { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--hp-radius); font-size: 0.9rem; }
  .banner.live { background: rgba(59,130,246,0.12); border: 1px solid rgba(59,130,246,0.35); animation: pulse 1.6s ease-in-out infinite; }
  .banner.pending { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.4); }
  .banner-text { flex: 1 1 220px; }
  .banner-actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .btn { border: none; border-radius: 999px; padding: 5px 14px; background: var(--primary-color); color: var(--text-primary-color, #fff); font-size: 0.85rem; }
  .btn.ghost { background: none; color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  @keyframes pulse { 50% { opacity: 0.7; } }
  @media (prefers-reduced-motion: reduce) { .banner.live { animation: none; } }

  .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  @container (max-width: 640px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .stat { position: relative; overflow: hidden; color: #fff; border-radius: var(--hp-radius); padding: 14px; cursor: pointer; transition: transform .2s, box-shadow .2s; }
  .stat:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.15); }
  .bg-icon { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); opacity: 0.15; --mdc-icon-size: 64px; }
  .stat-title { font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.85; }
  .stat-value { display: flex; align-items: baseline; margin-top: 4px; }
  .stat-value span { font-size: 1.9rem; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .trend { display: flex; align-items: center; gap: 4px; margin-top: 6px; font-size: 0.72rem; opacity: 0.85; }
  .trend ha-icon { --mdc-icon-size: 14px; }
  .spark { display: flex; align-items: flex-end; gap: 2px; height: 16px; margin-top: 8px; }
  .spark i { flex: 1; max-width: 8px; min-width: 3px; border-radius: 2px; background: rgba(255,255,255,0.45); }

  .grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  @container (max-width: 640px) { .grid2, .grid3 { grid-template-columns: minmax(0, 1fr); } }
  .panel { border: 1px solid var(--divider-color); border-radius: var(--hp-radius); padding: 12px 14px; background: var(--card-background-color); }
  .panel.accent { border-top: 3px solid var(--accent); }
  .panel-title { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 8px; }
  .panel-title.caps { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; }
  .row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--divider-color); font-size: 0.9rem; cursor: pointer; }
  .row:last-child { border-bottom: none; }
  .panel.small .row { font-size: 0.8rem; padding: 4px 0; }
  .row-label { display: flex; align-items: center; gap: 8px; color: var(--secondary-text-color); }
  .row-value { font-weight: 700; font-variant-numeric: tabular-nums; }

  .donut-wrap { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; justify-content: center; }
  .donut { width: 140px; height: 140px; flex: none; }
  .donut-value { font-size: 15px; font-weight: 700; fill: var(--primary-text-color); }
  .donut-unit { font-size: 8px; fill: var(--secondary-text-color); }
  .legend-list { flex: 1 1 180px; display: flex; flex-direction: column; gap: 6px; font-size: 0.88rem; }
  .leg { display: flex; align-items: center; }
  .leg b { margin-left: auto; font-variant-numeric: tabular-nums; }
  .leg.sub { padding-left: 16px; color: var(--secondary-text-color); font-size: 0.8rem; }
  .leg.total { border-top: 1px solid var(--divider-color); padding-top: 6px; font-weight: 600; }
  .leg.total b { font-size: 1.1rem; }

  .summary { display: flex; flex-wrap: wrap; gap: 6px 18px; padding: 10px 14px; border-radius: var(--hp-radius); background: var(--secondary-background-color); font-size: 0.85rem; color: var(--secondary-text-color); }
  .summary b { color: var(--primary-text-color); }
  .note { font-size: 0.8rem; color: var(--secondary-text-color); }
  .empty { text-align: center; padding: 32px 12px; color: var(--secondary-text-color); }
  .empty ha-icon { --mdc-icon-size: 40px; }

  .minis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
  @container (max-width: 480px) { .minis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .mini { text-align: center; border: 1px solid var(--divider-color); border-radius: var(--hp-radius); padding: 10px; }
  .mini-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--secondary-text-color); }
  .mini-value { font-size: 1.4rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  .bodymap-wrap { display: flex; justify-content: center; }
  .bodymap { width: 100%; max-width: 420px; max-height: 65vh; }
  .body-fill { fill: var(--primary-color); fill-opacity: 0.08; }
  .body-outline { fill: none; stroke: var(--primary-color); stroke-width: 28; stroke-linejoin: round; }
  .sep { stroke: var(--card-background-color); stroke-width: 4; stroke-opacity: 0.6; }
  .pill { fill: var(--card-background-color); fill-opacity: 0.92; stroke-width: 2.5; }
  .pill-label { font-size: 39px; font-weight: 600; fill: var(--secondary-text-color); }
  .pill-value { font-size: 50px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .seg-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 16px; font-size: 0.8rem; color: var(--secondary-text-color); }
  .leg-item { display: inline-flex; align-items: center; }
  .seg-toggle { display: flex; justify-content: center; gap: 4px; }
  .seg-btn, .range { border: none; background: var(--secondary-background-color); color: var(--secondary-text-color); border-radius: 999px; padding: 6px 14px; font-size: 0.8rem; }
  .seg-btn.active, .range.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }

  .range-bar { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
  .range { padding: 4px 10px; }
  .charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  @container (max-width: 640px) { .charts { grid-template-columns: minmax(0, 1fr); } }
  .chart .panel-title { font-size: 0.9rem; }
  .chart-latest { margin-left: auto; font-variant-numeric: tabular-nums; color: var(--secondary-text-color); font-weight: 500; }
  .chart select { margin-left: auto; font: inherit; font-size: 0.8rem; background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 6px; padding: 2px 6px; }
  .chart-box { position: relative; }
  .chart-box svg { width: 100%; height: auto; display: block; touch-action: pan-y; }
  .gridline { stroke: var(--divider-color); stroke-width: 1; }
  .axis { font-size: 9px; fill: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .cross { stroke: var(--secondary-text-color); stroke-opacity: 0.5; stroke-dasharray: 3 3; }
  .tip { display: none; position: absolute; top: 0; transform: translateX(-50%); pointer-events: none; background: var(--card-background-color); border: 1px solid var(--divider-color); box-shadow: 0 4px 12px rgba(0,0,0,0.15); border-radius: 8px; padding: 6px 8px; font-size: 0.75rem; white-space: nowrap; z-index: 1; }
  .tip-date { color: var(--secondary-text-color); margin-bottom: 2px; }
  .chart-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 0.75rem; color: var(--secondary-text-color); margin-top: 4px; }
  .chart-empty { padding: 30px 0; text-align: center; font-size: 0.85rem; color: var(--secondary-text-color); }
`;

// ---------------------------------------------------------------------------
// Visual editor
// ---------------------------------------------------------------------------

const EDITOR_SCHEMA = [
  { name: "person", selector: { device: { integration: "hume_pod", model: "Body Pod profile" } } },
  {
    name: "view",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "overview", label: "Overview" },
          { value: "body", label: "Body map" },
          { value: "trends", label: "Trends" },
        ],
      },
    },
  },
  { name: "show_tabs", selector: { boolean: {} } },
  { name: "title", selector: { text: {} } },
];
const EDITOR_LABELS = {
  person: "Person (leave empty to switch between everyone)",
  view: "Opens on",
  show_tabs: "Show tabs",
  title: "Title",
};

class HumePodCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => EDITOR_LABELS[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        for (const k of Object.keys(config)) if (config[k] === "" || config[k] === undefined) delete config[k];
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = { view: "overview", show_tabs: true, ...this._config };
  }
}

if (!customElements.get("hume-pod-card")) {
  customElements.define("hume-pod-card", HumePodCard);
  customElements.define("hume-pod-card-editor", HumePodCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "hume-pod-card",
    name: "Hume Body Pod",
    description: "Body composition overview, segmental body map and trends from a Hume Body Pod.",
    preview: false,
    documentationURL: "https://github.com/danfulton72/hume_pod_ha",
  });
  console.info(`%c HUME-POD-CARD %c ${CARD_VERSION} `, "color:#fff;background:#0d9488;font-weight:700", "color:#0d9488");
}
