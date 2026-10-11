// The shapes of events, once as signed distance functions for the shaders (GLSL and WGSL,
// the same maths) and once as Canvas 2D paths. Index order is SYMBOLS (scene.ts, Python's
// styling.SYMBOLS): 0 circle, 1 square, 2 diamond, 3 triangle, 4 triangle-down, 5 cross,
// 6 x, 7 tick, 8-12 the open versions of 0-4. Shapes have about the area of the circle of
// the same diameter, so sizes compare across shapes. Screen y points down.

export const SYMBOL_GLSL = /* glsl */ `
float sdBox(vec2 p, vec2 b) {
  vec2 d = abs(p) - b;
  return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}
float sdTri(vec2 p, float r) {
  const float k = 1.7320508;
  p.x = abs(p.x) - r;
  p.y = p.y + r / k;
  if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0;
  p.x -= clamp(p.x, -2.0 * r, 0.0);
  return -length(p) * sign(p.y);
}
float symbolSdf(vec2 p, float r, float s) {
  int k = int(s + 0.5);
  bool open = k >= 8;
  int b = open ? k - 8 : k;
  float d;
  if (b == 0) d = length(p) - r;
  else if (b == 1) d = sdBox(p, vec2(r * 0.886));
  else if (b == 2) d = (abs(p.x) + abs(p.y) - r * 1.25) * 0.7071;
  else if (b == 3) d = sdTri(vec2(p.x, -p.y), r * 1.1);
  else if (b == 4) d = sdTri(vec2(p.x, p.y), r * 1.1);
  else if (b == 5) d = min(sdBox(p, vec2(r, r * 0.3)), sdBox(p, vec2(r * 0.3, r)));
  else if (b == 6) {
    vec2 q = vec2(p.x + p.y, p.y - p.x) * 0.7071;
    d = min(sdBox(q, vec2(r * 1.1, r * 0.28)), sdBox(q, vec2(r * 0.28, r * 1.1)));
  } else d = sdBox(p, vec2(max(0.8, r * 0.2), r * 1.2));
  if (open) d = abs(d + 0.9) - 0.9;
  return d;
}
`;

export const SYMBOL_WGSL = /* wgsl */ `
fn sdBox(p: vec2f, b: vec2f) -> f32 {
  let d = abs(p) - b;
  return length(max(d, vec2f(0.0))) + min(max(d.x, d.y), 0.0);
}
fn sdTri(p0: vec2f, r: f32) -> f32 {
  let k = 1.7320508;
  var p = vec2f(abs(p0.x) - r, p0.y + r / k);
  if (p.x + k * p.y > 0.0) { p = vec2f(p.x - k * p.y, -k * p.x - p.y) / 2.0; }
  p.x = p.x - clamp(p.x, -2.0 * r, 0.0);
  return -length(p) * sign(p.y);
}
fn symbolSdf(p: vec2f, r: f32, s: f32) -> f32 {
  let k = i32(s + 0.5);
  let open = k >= 8;
  var b = k;
  if (open) { b = k - 8; }
  var d: f32;
  if (b == 0) { d = length(p) - r; }
  else if (b == 1) { d = sdBox(p, vec2f(r * 0.886)); }
  else if (b == 2) { d = (abs(p.x) + abs(p.y) - r * 1.25) * 0.7071; }
  else if (b == 3) { d = sdTri(vec2f(p.x, -p.y), r * 1.1); }
  else if (b == 4) { d = sdTri(vec2f(p.x, p.y), r * 1.1); }
  else if (b == 5) { d = min(sdBox(p, vec2f(r, r * 0.3)), sdBox(p, vec2f(r * 0.3, r))); }
  else if (b == 6) {
    let q = vec2f(p.x + p.y, p.y - p.x) * 0.7071;
    d = min(sdBox(q, vec2f(r * 1.1, r * 0.28)), sdBox(q, vec2f(r * 0.28, r * 1.1)));
  } else { d = sdBox(p, vec2f(max(0.8, r * 0.2), r * 1.2)); }
  if (open) { d = abs(d + 0.9) - 0.9; }
  return d;
}
`;

/** Add symbol `s` of radius `r` centred at (x, y) to a path (Canvas 2D, legends). */
export function tracePath(path: Path2D | CanvasRenderingContext2D, s: number, x: number, y: number, r: number): void {
  const b = s >= 8 ? s - 8 : s;
  const poly = (pts: [number, number][]) => {
    path.moveTo(x + pts[0][0], y + pts[0][1]);
    for (let i = 1; i < pts.length; i++) path.lineTo(x + pts[i][0], y + pts[i][1]);
    path.closePath();
  };
  if (b === 0) {
    path.moveTo(x + r, y);
    path.arc(x, y, r, 0, Math.PI * 2);
  } else if (b === 1) {
    const h = r * 0.886;
    poly([[-h, -h], [h, -h], [h, h], [-h, h]]);
  } else if (b === 2) {
    const h = r * 1.25;
    poly([[0, -h], [h, 0], [0, h], [-h, 0]]);
  } else if (b === 3 || b === 4) {
    const R = r * 1.1;
    const up = b === 3 ? -1 : 1;
    const ry = (R * 2) / Math.sqrt(3); // circumradius of the triangle iq's sdTri draws
    poly([[0, up * ry], [R, -up * ry / 2], [-R, -up * ry / 2]]);
  } else if (b === 5) {
    poly(plus(r, r * 0.3));
  } else if (b === 6) {
    poly(plus(r * 1.1, r * 0.28).map(([u, v]) => [(u - v) * Math.SQRT1_2, (u + v) * Math.SQRT1_2]));
  } else {
    const w = Math.max(0.8, r * 0.2);
    poly([[-w, -r * 1.2], [w, -r * 1.2], [w, r * 1.2], [-w, r * 1.2]]);
  }
}

/** The outline of a plus sign with arms `l` long and `w` wide (half sizes). */
function plus(l: number, w: number): [number, number][] {
  return [[-w, -l], [w, -l], [w, -w], [l, -w], [l, w], [w, w], [w, l], [-w, l], [-w, w], [-l, w], [-l, -w], [-w, -w]];
}

export function isOpen(s: number): boolean {
  return s >= 8;
}
