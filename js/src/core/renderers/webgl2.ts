// WebGL2 backend: one instanced draw per layer (marks) and one for each route layer
// (segments). The reference backend; WebGPU draws the same.

import type { RendererKind } from "../types";
import { type BarLayerDraw, type FrameDraw, type MarkLayerDraw, type Renderer, type RendererOptions, type SegmentDraw } from "./renderer";
import { SYMBOL_GLSL } from "./symbols";

const MARK_VS = /* glsl */ `#version 300 es
precision highp float;
in float a_x;
in float a_lane;
in float a_dy;
in float a_size;
in vec4 a_color;
in vec4 a_sf;
uniform vec2 u_canvas;
uniform vec2 u_plot;
uniform float u_offset;
uniform float u_scale;
uniform float u_laneTop;
uniform float u_laneH;
out vec2 v_local;
out float v_r;
out vec4 v_color;
out float v_symbol;
out float v_flags;
void main() {
  int c = gl_VertexID % 6;
  vec2 corner = vec2((c == 1 || c == 2 || c == 4) ? 1.0 : -1.0, (c == 2 || c == 4 || c == 5) ? 1.0 : -1.0);
  float half_ = a_size * 0.5 + 4.0;
  vec2 center = vec2(u_plot.x + (a_x - u_offset) * u_scale, u_laneTop + (a_lane + 0.5) * u_laneH + a_dy);
  vec2 px = center + corner * half_;
  gl_Position = vec4(px.x / u_canvas.x * 2.0 - 1.0, 1.0 - px.y / u_canvas.y * 2.0, 0.0, 1.0);
  v_local = corner * half_;
  v_r = a_size * 0.5;
  v_color = a_color;
  v_symbol = a_sf.x;
  v_flags = a_sf.y;
}`;

const MARK_FS = /* glsl */ `#version 300 es
precision highp float;
in vec2 v_local;
in float v_r;
in vec4 v_color;
in float v_symbol;
in float v_flags;
uniform vec3 u_bg;
uniform vec3 u_sel;
uniform vec3 u_hov;
uniform float u_fade;
uniform float u_aa;
out vec4 outColor;
${SYMBOL_GLSL}
void main() {
  float d = symbolSdf(v_local, v_r, v_symbol);
  int flags = int(v_flags + 0.5);
  bool selected = (flags & 1) != 0;
  bool hovered = (flags & 2) != 0;
  float fill = 1.0 - smoothstep(-u_aa, u_aa, d);
  vec3 rgb = v_color.rgb;
  float a = v_color.a;
  if (v_symbol < 4.5) rgb = mix(rgb, u_bg, smoothstep(-1.8, -0.7, d) * 0.4);
  if (u_fade > 0.5 && !selected) a *= 0.2;
  vec4 col = vec4(rgb * a * fill, a * fill);
  if (selected || hovered) {
    float ring = 1.0 - smoothstep(0.9 - u_aa, 0.9 + u_aa, abs(d - 2.0));
    vec3 rc = hovered ? u_hov : u_sel;
    col = vec4(rc, 1.0) * ring + col * (1.0 - ring);
  }
  if (col.a < 0.002) discard;
  outColor = col;
}`;

// Bars: a rounded rectangle from start to end (at least 1 px wide, 1 px short of its end so
// abutting bars stay apart), or a diamond for a milestone. The part past the progress point
// is lighter; an open bar fades out at its end.
const BAR_VS = /* glsl */ `#version 300 es
precision highp float;
in vec2 a_x;
in vec4 a_geom;
in vec4 a_color;
in vec4 a_flags;
uniform vec2 u_canvas;
uniform vec4 u_plot;
uniform float u_offset;
uniform float u_scale;
uniform float u_laneTop;
uniform float u_laneH;
uniform float u_fill;
uniform float u_maxBar;
out vec2 v_local;
out vec2 v_half;
out vec4 v_color;
out float v_flags;
out float v_prog;
void main() {
  int c = gl_VertexID % 6;
  vec2 corner = vec2((c == 1 || c == 2 || c == 4) ? 1.0 : -1.0, (c == 2 || c == 4 || c == 5) ? 1.0 : -1.0);
  float x0 = u_plot.x + (a_x.x - u_offset) * u_scale;
  float x1 = u_plot.x + (a_x.y - u_offset) * u_scale;
  float rows = max(1.0, a_geom.z);
  float pitch = u_laneH * u_fill / rows;
  float h = min(pitch * (rows > 1.5 ? 0.85 : 1.0), u_maxBar);
  if (a_geom.w < -1.5) h *= -a_geom.w - 2.0;
  float cy = u_laneTop + (a_geom.x + 0.5) * u_laneH + (a_geom.y - (rows - 1.0) * 0.5) * pitch;
  int f = int(a_flags.x + 0.5);
  vec2 half_;
  vec2 center;
  if ((f & 4) != 0) {
    half_ = vec2(h * 0.62);
    center = vec2(x0, cy);
  } else {
    // keep far-off ends near the plot (float precision); they are outside the scissor
    float a = max(x0, u_plot.x - 8.0);
    float b = min(max(x1 - (x1 - x0 > 3.0 ? 1.0 : 0.0), x0 + 1.0), u_plot.x + u_plot.z + 8.0);
    b = max(b, a + 1.0);
    half_ = vec2((b - a) * 0.5, h * 0.5);
    center = vec2((a + b) * 0.5, cy);
  }
  vec2 ext = half_ + 3.0;
  vec2 px = center + corner * ext;
  gl_Position = vec4(px.x / u_canvas.x * 2.0 - 1.0, 1.0 - px.y / u_canvas.y * 2.0, 0.0, 1.0);
  v_local = corner * ext;
  v_half = half_;
  v_color = a_color;
  v_flags = a_flags.x;
  v_prog = a_geom.w < 0.0 ? 1e9 : x0 + a_geom.w * (x1 - x0) - center.x;
}`;

const BAR_FS = /* glsl */ `#version 300 es
precision highp float;
in vec2 v_local;
in vec2 v_half;
in vec4 v_color;
in float v_flags;
in float v_prog;
uniform vec3 u_bg;
uniform vec3 u_sel;
uniform float u_fade;
uniform float u_aa;
out vec4 outColor;
float sdRound(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main() {
  int f = int(v_flags + 0.5);
  bool milestone = (f & 4) != 0;
  float d = milestone
    ? (abs(v_local.x) + abs(v_local.y) - v_half.x) * 0.7071
    : sdRound(v_local, v_half, min(2.5, min(v_half.x, v_half.y)));
  float fill = 1.0 - smoothstep(-u_aa, u_aa, d);
  vec3 rgb = v_color.rgb;
  float a = v_color.a;
  if (!milestone && v_local.x > v_prog) rgb = mix(rgb, u_bg, 0.55);
  if ((f & 8) != 0) a *= clamp((v_half.x - v_local.x) / 48.0, 0.12, 1.0);
  bool selected = (f & 1) != 0;
  if (u_fade > 0.5 && !selected) a *= 0.22;
  vec4 col = vec4(rgb * a * fill, a * fill);
  if (selected) {
    float ring = 1.0 - smoothstep(0.9 - u_aa, 0.9 + u_aa, abs(d - 1.8));
    col = vec4(u_sel, 1.0) * ring + col * (1.0 - ring);
  }
  if (col.a < 0.002) discard;
  outColor = col;
}`;

const SEG_VS = /* glsl */ `#version 300 es
precision highp float;
in vec4 a_seg;
in vec4 a_color;
uniform vec2 u_canvas;
uniform float u_width;
out float v_across;
out vec4 v_color;
void main() {
  int c = gl_VertexID % 6;
  float along = (c == 1 || c == 2 || c == 4) ? 1.0 : 0.0;
  float side = (c == 2 || c == 4 || c == 5) ? 1.0 : -1.0;
  vec2 a = a_seg.xy;
  vec2 b = a_seg.zw;
  vec2 dir = b - a;
  float len = max(length(dir), 1e-4);
  dir /= len;
  vec2 n = vec2(-dir.y, dir.x);
  float half_ = u_width * 0.5 + 1.0;
  vec2 px = mix(a, b, along) + n * side * half_;
  gl_Position = vec4(px.x / u_canvas.x * 2.0 - 1.0, 1.0 - px.y / u_canvas.y * 2.0, 0.0, 1.0);
  v_across = side * half_;
  v_color = a_color;
}`;

const SEG_FS = /* glsl */ `#version 300 es
precision highp float;
in float v_across;
in vec4 v_color;
uniform float u_width;
out vec4 outColor;
void main() {
  float a = v_color.a * (1.0 - smoothstep(u_width * 0.5 - 0.5, u_width * 0.5 + 0.5, abs(v_across)));
  if (a < 0.002) discard;
  outColor = vec4(v_color.rgb * a, a);
}`;

interface GLBuf {
  buffer: WebGLBuffer;
  version: number;
  bytes: number;
}

interface Program {
  program: WebGLProgram;
  attrs: Record<string, number>;
  uniforms: Record<string, WebGLUniformLocation | null>;
}

export class WebGL2Renderer implements Renderer {
  readonly kind: RendererKind = "webgl2";
  readonly description: string;
  onFailure: ((reason: string) => void) | null = null;
  private dpr = 1;
  private cssW = 1;
  private cssH = 1;
  private readonly marks: Program;
  private readonly segs: Program;
  private readonly bars: Program;
  private readonly buffers = new Map<string, GLBuf>();
  private readonly vaos = new Map<string, WebGLVertexArrayObject>();
  private readonly segBuffer: { coords: WebGLBuffer; colors: WebGLBuffer; vao: WebGLVertexArrayObject };

  static create(canvas: HTMLCanvasElement, options: RendererOptions): WebGL2Renderer | null {
    const gl = canvas.getContext("webgl2", {
      antialias: false,
      premultipliedAlpha: true,
      alpha: true,
      failIfMajorPerformanceCaveat: !options.allowSoftware,
    });
    if (!gl) return null;
    return new WebGL2Renderer(canvas, gl);
  }

  private constructor(
    readonly canvas: HTMLCanvasElement,
    private readonly gl: WebGL2RenderingContext,
  ) {
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    this.description = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "WebGL2";
    this.marks = this.program(MARK_VS, MARK_FS,
      ["a_x", "a_lane", "a_dy", "a_size", "a_color", "a_sf"],
      ["u_canvas", "u_plot", "u_offset", "u_scale", "u_laneTop", "u_laneH", "u_bg", "u_sel", "u_hov", "u_fade", "u_aa"]);
    this.segs = this.program(SEG_VS, SEG_FS, ["a_seg", "a_color"], ["u_canvas", "u_width"]);
    this.bars = this.program(BAR_VS, BAR_FS, ["a_x", "a_geom", "a_color", "a_flags"],
      ["u_canvas", "u_plot", "u_offset", "u_scale", "u_laneTop", "u_laneH", "u_fill", "u_maxBar", "u_bg", "u_sel", "u_fade", "u_aa"]);
    const coords = gl.createBuffer()!;
    const colors = gl.createBuffer()!;
    const vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);
    this.attrib(coords, this.segs.attrs.a_seg, 4, gl.FLOAT, false);
    this.attrib(colors, this.segs.attrs.a_color, 4, gl.UNSIGNED_BYTE, true);
    gl.bindVertexArray(null);
    this.segBuffer = { coords, colors, vao };
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.onFailure?.("WebGL context lost");
    });
  }

  private program(vs: string, fs: string, attrs: string[], uniforms: string[]): Program {
    const gl = this.gl;
    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader error");
      return s;
    };
    const p = gl.createProgram()!;
    gl.attachShader(p, compile(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? "link error");
    return {
      program: p,
      attrs: Object.fromEntries(attrs.map((a) => [a, gl.getAttribLocation(p, a)])),
      uniforms: Object.fromEntries(uniforms.map((u) => [u, gl.getUniformLocation(p, u)])),
    };
  }

  private attrib(buffer: WebGLBuffer, loc: number, size: number, type: number, normalized: boolean): void {
    const gl = this.gl;
    if (loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, type, normalized, 0, 0);
    gl.vertexAttribDivisor(loc, 1);
  }

  resize(cssWidth: number, cssHeight: number, dpr: number): void {
    this.cssW = Math.max(1, cssWidth);
    this.cssH = Math.max(1, cssHeight);
    this.dpr = dpr;
    this.canvas.width = Math.max(1, Math.round(this.cssW * dpr));
    this.canvas.height = Math.max(1, Math.round(this.cssH * dpr));
  }

  private upload(key: string, attr: { data: ArrayBufferView; version: number }): { buffer: WebGLBuffer; changed: boolean } {
    const gl = this.gl;
    let b = this.buffers.get(key);
    if (b && b.version === attr.version && b.bytes === attr.data.byteLength) return { buffer: b.buffer, changed: false };
    if (!b) {
      b = { buffer: gl.createBuffer()!, version: -1, bytes: 0 };
      this.buffers.set(key, b);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, b.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, attr.data, gl.DYNAMIC_DRAW);
    b.version = attr.version;
    b.bytes = attr.data.byteLength;
    return { buffer: b.buffer, changed: true };
  }

  render(frame: FrameDraw): void {
    const gl = this.gl;
    if (gl.isContextLost()) return;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.disable(gl.SCISSOR_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    const { plot } = frame;
    gl.enable(gl.SCISSOR_TEST);
    gl.scissor(
      Math.round(plot.x * this.dpr),
      Math.round(this.canvas.height - (plot.y + plot.h) * this.dpr),
      Math.max(0, Math.round(plot.w * this.dpr)),
      Math.max(0, Math.round(plot.h * this.dpr)),
    );
    for (const b of frame.bars) this.drawBars(b, frame);
    for (const s of frame.segments) this.drawSegments(s);
    for (const layer of frame.layers) this.drawMarks(layer, frame);
    gl.disable(gl.SCISSOR_TEST);
  }

  private drawSegments(s: SegmentDraw): void {
    if (!s.count) return;
    const gl = this.gl;
    gl.useProgram(this.segs.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.segBuffer.coords);
    gl.bufferData(gl.ARRAY_BUFFER, s.coords.subarray(0, s.count * 4), gl.STREAM_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.segBuffer.colors);
    gl.bufferData(gl.ARRAY_BUFFER, s.colors.subarray(0, s.count * 4), gl.STREAM_DRAW);
    gl.uniform2f(this.segs.uniforms.u_canvas, this.cssW, this.cssH);
    gl.uniform1f(this.segs.uniforms.u_width, s.width);
    gl.bindVertexArray(this.segBuffer.vao);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, s.count);
    gl.bindVertexArray(null);
  }

  private drawBars(layer: BarLayerDraw, frame: FrameDraw): void {
    if (!layer.count) return;
    const gl = this.gl;
    const p = this.bars;
    gl.useProgram(p.program);
    const k = layer.key;
    const ups = [
      this.upload(`${k}:x`, layer.x),
      this.upload(`${k}:geom`, layer.geom),
      this.upload(`${k}:color`, layer.color),
      this.upload(`${k}:flags`, layer.flags),
    ];
    let vao = this.vaos.get(k);
    if (!vao || ups.some((u) => u.changed)) {
      if (!vao) {
        vao = gl.createVertexArray()!;
        this.vaos.set(k, vao);
      }
      gl.bindVertexArray(vao);
      this.attrib(ups[0].buffer, p.attrs.a_x, 2, gl.FLOAT, false);
      this.attrib(ups[1].buffer, p.attrs.a_geom, 4, gl.FLOAT, false);
      this.attrib(ups[2].buffer, p.attrs.a_color, 4, gl.UNSIGNED_BYTE, true);
      this.attrib(ups[3].buffer, p.attrs.a_flags, 4, gl.UNSIGNED_BYTE, false);
    }
    gl.bindVertexArray(vao);
    const u = p.uniforms;
    gl.uniform2f(u.u_canvas, this.cssW, this.cssH);
    gl.uniform4f(u.u_plot, frame.plot.x, frame.plot.y, frame.plot.w, frame.plot.h);
    gl.uniform1f(u.u_offset, layer.offset);
    gl.uniform1f(u.u_scale, layer.scale);
    gl.uniform1f(u.u_laneTop, layer.laneTop);
    gl.uniform1f(u.u_laneH, layer.laneHeight);
    gl.uniform1f(u.u_fill, layer.fill);
    gl.uniform1f(u.u_maxBar, layer.maxBar);
    gl.uniform3f(u.u_bg, ...frame.background);
    gl.uniform3f(u.u_sel, ...frame.selection);
    gl.uniform1f(u.u_fade, layer.fade ? 1 : 0);
    gl.uniform1f(u.u_aa, 0.5 + 0.5 / this.dpr);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, layer.count);
    gl.bindVertexArray(null);
  }

  private drawMarks(layer: MarkLayerDraw, frame: FrameDraw): void {
    if (!layer.count) return;
    const gl = this.gl;
    const p = this.marks;
    gl.useProgram(p.program);
    const k = layer.key;
    const ups = [
      this.upload(`${k}:x`, layer.x),
      this.upload(`${k}:lane`, layer.lane),
      this.upload(`${k}:dy`, layer.dy),
      this.upload(`${k}:size`, layer.size),
      this.upload(`${k}:color`, layer.color),
      this.upload(`${k}:sf`, layer.sf),
    ];
    let vao = this.vaos.get(k);
    if (!vao || ups.some((u) => u.changed)) {
      if (!vao) {
        vao = gl.createVertexArray()!;
        this.vaos.set(k, vao);
      }
      gl.bindVertexArray(vao);
      this.attrib(ups[0].buffer, p.attrs.a_x, 1, gl.FLOAT, false);
      this.attrib(ups[1].buffer, p.attrs.a_lane, 1, gl.FLOAT, false);
      this.attrib(ups[2].buffer, p.attrs.a_dy, 1, gl.FLOAT, false);
      this.attrib(ups[3].buffer, p.attrs.a_size, 1, gl.FLOAT, false);
      this.attrib(ups[4].buffer, p.attrs.a_color, 4, gl.UNSIGNED_BYTE, true);
      this.attrib(ups[5].buffer, p.attrs.a_sf, 4, gl.UNSIGNED_BYTE, false);
    }
    gl.bindVertexArray(vao);
    const u = p.uniforms;
    gl.uniform2f(u.u_canvas, this.cssW, this.cssH);
    gl.uniform2f(u.u_plot, frame.plot.x, frame.plot.y);
    gl.uniform1f(u.u_offset, layer.offset);
    gl.uniform1f(u.u_scale, layer.scale);
    gl.uniform1f(u.u_laneTop, layer.laneTop);
    gl.uniform1f(u.u_laneH, layer.laneHeight);
    gl.uniform3f(u.u_bg, ...frame.background);
    gl.uniform3f(u.u_sel, ...frame.selection);
    gl.uniform3f(u.u_hov, ...frame.hover);
    gl.uniform1f(u.u_fade, layer.fade ? 1 : 0);
    gl.uniform1f(u.u_aa, 0.5 + 0.5 / this.dpr);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, layer.count);
    gl.bindVertexArray(null);
  }

  async finish(): Promise<void> {
    const px = new Uint8Array(4);
    this.gl.readPixels(0, 0, 1, 1, this.gl.RGBA, this.gl.UNSIGNED_BYTE, px);
  }

  retain(keys: Set<string>): void {
    for (const [key, b] of [...this.buffers]) {
      if (!keys.has(key.slice(0, key.lastIndexOf(":")))) {
        this.gl.deleteBuffer(b.buffer);
        this.buffers.delete(key);
      }
    }
    for (const [key, vao] of [...this.vaos]) {
      if (!keys.has(key)) {
        this.gl.deleteVertexArray(vao);
        this.vaos.delete(key);
      }
    }
  }

  destroy(): void {
    this.retain(new Set());
    this.gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}
