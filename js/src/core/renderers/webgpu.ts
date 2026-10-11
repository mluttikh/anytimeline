// WebGPU backend: the same drawing as WebGL2 (instanced marks, then route segments under
// them), in one render pass.

import type { RendererKind } from "../types";
import type { BarLayerDraw, FrameDraw, MarkLayerDraw, Renderer, RendererOptions, SegmentDraw } from "./renderer";
import { SYMBOL_WGSL } from "./symbols";

const MARKS_WGSL = /* wgsl */ `
struct U {
  canvas: vec2f, plot: vec2f,
  offset: f32, scale: f32, laneTop: f32, laneH: f32,
  bg: vec4f, sel: vec4f, hov: vec4f,
  fade: f32, aa: f32, pad0: f32, pad1: f32,
};
@group(0) @binding(0) var<uniform> u: U;
struct VOut {
  @builtin(position) pos: vec4f,
  @location(0) local: vec2f,
  @location(1) r: f32,
  @location(2) color: vec4f,
  @location(3) @interpolate(flat) sym: f32,
  @location(4) @interpolate(flat) flags: f32,
};
@vertex fn vs(@builtin(vertex_index) vi: u32, @location(0) x: f32, @location(1) lane: f32,
              @location(2) dy: f32, @location(3) size: f32, @location(4) color: vec4f,
              @location(5) sf: vec4u) -> VOut {
  let c = vi % 6u;
  var corner = vec2f(-1.0, -1.0);
  if (c == 1u || c == 2u || c == 4u) { corner.x = 1.0; }
  if (c == 2u || c == 4u || c == 5u) { corner.y = 1.0; }
  let half = size * 0.5 + 4.0;
  let center = vec2f(u.plot.x + (x - u.offset) * u.scale, u.laneTop + (lane + 0.5) * u.laneH + dy);
  let px = center + corner * half;
  var o: VOut;
  o.pos = vec4f(px.x / u.canvas.x * 2.0 - 1.0, 1.0 - px.y / u.canvas.y * 2.0, 0.0, 1.0);
  o.local = corner * half;
  o.r = size * 0.5;
  o.color = color;
  o.sym = f32(sf.x);
  o.flags = f32(sf.y);
  return o;
}
${SYMBOL_WGSL}
@fragment fn fs(i: VOut) -> @location(0) vec4f {
  let d = symbolSdf(i.local, i.r, i.sym);
  let flags = u32(i.flags + 0.5);
  let selected = (flags & 1u) != 0u;
  let hovered = (flags & 2u) != 0u;
  let fill = 1.0 - smoothstep(-u.aa, u.aa, d);
  var rgb = i.color.rgb;
  var a = i.color.a;
  if (i.sym < 4.5) { rgb = mix(rgb, u.bg.rgb, smoothstep(-1.8, -0.7, d) * 0.4); }
  if (u.fade > 0.5 && !selected) { a = a * 0.2; }
  var col = vec4f(rgb * a * fill, a * fill);
  if (selected || hovered) {
    let ring = 1.0 - smoothstep(0.9 - u.aa, 0.9 + u.aa, abs(d - 2.0));
    var rc = u.sel.rgb;
    if (hovered) { rc = u.hov.rgb; }
    col = vec4f(rc, 1.0) * ring + col * (1.0 - ring);
  }
  if (col.a < 0.002) { discard; }
  return col;
}`;

// Bars: the same drawing as WebGL2's BAR_VS / BAR_FS.
const BARS_WGSL = /* wgsl */ `
struct U {
  canvas: vec2f, pad0: vec2f,
  plot: vec4f,
  offset: f32, scale: f32, laneTop: f32, laneH: f32,
  fill: f32, maxBar: f32, fade: f32, aa: f32,
  bg: vec4f, sel: vec4f,
};
@group(0) @binding(0) var<uniform> u: U;
struct VOut {
  @builtin(position) pos: vec4f,
  @location(0) local: vec2f,
  @location(1) half: vec2f,
  @location(2) color: vec4f,
  @location(3) @interpolate(flat) flags: f32,
  @location(4) prog: f32,
};
@vertex fn vs(@builtin(vertex_index) vi: u32, @location(0) x: vec2f, @location(1) geom: vec4f,
              @location(2) color: vec4f, @location(3) flags: vec4u) -> VOut {
  let c = vi % 6u;
  var corner = vec2f(-1.0, -1.0);
  if (c == 1u || c == 2u || c == 4u) { corner.x = 1.0; }
  if (c == 2u || c == 4u || c == 5u) { corner.y = 1.0; }
  let x0 = u.plot.x + (x.x - u.offset) * u.scale;
  let x1 = u.plot.x + (x.y - u.offset) * u.scale;
  let rows = max(1.0, geom.z);
  let pitch = u.laneH * u.fill / rows;
  var h = pitch;
  if (rows > 1.5) { h = pitch * 0.85; }
  h = min(h, u.maxBar);
  let cy = u.laneTop + (geom.x + 0.5) * u.laneH + (geom.y - (rows - 1.0) * 0.5) * pitch;
  let f = flags.x;
  var half: vec2f;
  var center: vec2f;
  if ((f & 4u) != 0u) {
    half = vec2f(h * 0.62);
    center = vec2f(x0, cy);
  } else {
    let a = max(x0, u.plot.x - 8.0);
    var gap = 0.0;
    if (x1 - x0 > 3.0) { gap = 1.0; }
    var b = min(max(x1 - gap, x0 + 1.0), u.plot.x + u.plot.z + 8.0);
    b = max(b, a + 1.0);
    half = vec2f((b - a) * 0.5, h * 0.5);
    center = vec2f((a + b) * 0.5, cy);
  }
  let ext = half + 3.0;
  let px = center + corner * ext;
  var o: VOut;
  o.pos = vec4f(px.x / u.canvas.x * 2.0 - 1.0, 1.0 - px.y / u.canvas.y * 2.0, 0.0, 1.0);
  o.local = corner * ext;
  o.half = half;
  o.color = color;
  o.flags = f32(f);
  if (geom.w < 0.0) { o.prog = 1e9; } else { o.prog = x0 + geom.w * (x1 - x0) - center.x; }
  return o;
}
fn sdRound(p: vec2f, b: vec2f, r: f32) -> f32 {
  let q = abs(p) - b + r;
  return length(max(q, vec2f(0.0))) + min(max(q.x, q.y), 0.0) - r;
}
@fragment fn fs(i: VOut) -> @location(0) vec4f {
  let f = u32(i.flags + 0.5);
  let milestone = (f & 4u) != 0u;
  var d: f32;
  if (milestone) { d = (abs(i.local.x) + abs(i.local.y) - i.half.x) * 0.7071; }
  else { d = sdRound(i.local, i.half, min(2.5, min(i.half.x, i.half.y))); }
  let fill = 1.0 - smoothstep(-u.aa, u.aa, d);
  var rgb = i.color.rgb;
  var a = i.color.a;
  if (!milestone && i.local.x > i.prog) { rgb = mix(rgb, u.bg.rgb, 0.55); }
  if ((f & 8u) != 0u) { a = a * clamp((i.half.x - i.local.x) / 48.0, 0.12, 1.0); }
  let selected = (f & 1u) != 0u;
  if (u.fade > 0.5 && !selected) { a = a * 0.22; }
  var col = vec4f(rgb * a * fill, a * fill);
  if (selected) {
    let ring = 1.0 - smoothstep(0.9 - u.aa, 0.9 + u.aa, abs(d - 1.8));
    col = vec4f(u.sel.rgb, 1.0) * ring + col * (1.0 - ring);
  }
  if (col.a < 0.002) { discard; }
  return col;
}`;

const SEGMENTS_WGSL = /* wgsl */ `
struct U { canvas: vec2f, width: f32, pad: f32 };
@group(0) @binding(0) var<uniform> u: U;
struct VOut { @builtin(position) pos: vec4f, @location(0) across: f32, @location(1) color: vec4f };
@vertex fn vs(@builtin(vertex_index) vi: u32, @location(0) seg: vec4f, @location(1) color: vec4f) -> VOut {
  let c = vi % 6u;
  var along = 0.0;
  var side = -1.0;
  if (c == 1u || c == 2u || c == 4u) { along = 1.0; }
  if (c == 2u || c == 4u || c == 5u) { side = 1.0; }
  let a = seg.xy;
  let b = seg.zw;
  let dir = normalize(b - a + vec2f(1e-4, 0.0));
  let n = vec2f(-dir.y, dir.x);
  let half = u.width * 0.5 + 1.0;
  let px = mix(a, b, along) + n * side * half;
  var o: VOut;
  o.pos = vec4f(px.x / u.canvas.x * 2.0 - 1.0, 1.0 - px.y / u.canvas.y * 2.0, 0.0, 1.0);
  o.across = side * half;
  o.color = color;
  return o;
}
@fragment fn fs(i: VOut) -> @location(0) vec4f {
  let a = i.color.a * (1.0 - smoothstep(u.width * 0.5 - 0.5, u.width * 0.5 + 0.5, abs(i.across)));
  if (a < 0.002) { discard; }
  return vec4f(i.color.rgb * a, a);
}`;

const BLEND: GPUBlendState = {
  color: { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" },
  alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" },
};

interface GPUBuf {
  buffer: GPUBuffer;
  version: number;
  bytes: number;
}

export class WebGPURenderer implements Renderer {
  readonly kind: RendererKind = "webgpu";
  readonly description: string;
  onFailure: ((reason: string) => void) | null = null;
  private dpr = 1;
  private cssW = 1;
  private cssH = 1;
  private readonly marks: GPURenderPipeline;
  private readonly segments: GPURenderPipeline;
  private readonly barsPipeline: GPURenderPipeline;
  private readonly buffers = new Map<string, GPUBuf>();
  private readonly uniforms = new Map<string, { buffer: GPUBuffer; group: GPUBindGroup }>();
  private failed = false;

  static async create(canvas: HTMLCanvasElement, options: RendererOptions): Promise<WebGPURenderer | null> {
    if (!("gpu" in navigator) || !navigator.gpu) return null;
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) return null;
    const info = (adapter as GPUAdapter & { info?: GPUAdapterInfo }).info;
    if (!options.allowSoftware && (info as { isFallbackAdapter?: boolean } | undefined)?.isFallbackAdapter) return null;
    const device = await adapter.requestDevice();
    const context = canvas.getContext("webgpu");
    if (!context) {
      device.destroy();
      return null;
    }
    const format = navigator.gpu.getPreferredCanvasFormat();
    context.configure({ device, format, alphaMode: "premultiplied" });
    const name = info ? [info.vendor, info.architecture, info.description].filter(Boolean).join(" ") : "";
    return new WebGPURenderer(canvas, device, context, format, name || "WebGPU");
  }

  private constructor(
    readonly canvas: HTMLCanvasElement,
    private readonly device: GPUDevice,
    private readonly context: GPUCanvasContext,
    format: GPUTextureFormat,
    description: string,
  ) {
    this.description = description;
    const markModule = device.createShaderModule({ code: MARKS_WGSL });
    const f32 = (location: number): GPUVertexBufferLayout => ({
      arrayStride: 4,
      stepMode: "instance",
      attributes: [{ shaderLocation: location, offset: 0, format: "float32" }],
    });
    this.marks = device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module: markModule,
        entryPoint: "vs",
        buffers: [
          f32(0), f32(1), f32(2), f32(3),
          { arrayStride: 4, stepMode: "instance", attributes: [{ shaderLocation: 4, offset: 0, format: "unorm8x4" }] },
          { arrayStride: 4, stepMode: "instance", attributes: [{ shaderLocation: 5, offset: 0, format: "uint8x4" }] },
        ],
      },
      fragment: { module: markModule, entryPoint: "fs", targets: [{ format, blend: BLEND }] },
      primitive: { topology: "triangle-list" },
    });
    const segModule = device.createShaderModule({ code: SEGMENTS_WGSL });
    this.segments = device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module: segModule,
        entryPoint: "vs",
        buffers: [
          { arrayStride: 16, stepMode: "instance", attributes: [{ shaderLocation: 0, offset: 0, format: "float32x4" }] },
          { arrayStride: 4, stepMode: "instance", attributes: [{ shaderLocation: 1, offset: 0, format: "unorm8x4" }] },
        ],
      },
      fragment: { module: segModule, entryPoint: "fs", targets: [{ format, blend: BLEND }] },
      primitive: { topology: "triangle-list" },
    });
    const barModule = device.createShaderModule({ code: BARS_WGSL });
    this.barsPipeline = device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module: barModule,
        entryPoint: "vs",
        buffers: [
          { arrayStride: 8, stepMode: "instance", attributes: [{ shaderLocation: 0, offset: 0, format: "float32x2" }] },
          { arrayStride: 16, stepMode: "instance", attributes: [{ shaderLocation: 1, offset: 0, format: "float32x4" }] },
          { arrayStride: 4, stepMode: "instance", attributes: [{ shaderLocation: 2, offset: 0, format: "unorm8x4" }] },
          { arrayStride: 4, stepMode: "instance", attributes: [{ shaderLocation: 3, offset: 0, format: "uint8x4" }] },
        ],
      },
      fragment: { module: barModule, entryPoint: "fs", targets: [{ format, blend: BLEND }] },
      primitive: { topology: "triangle-list" },
    });
    device.lost.then((info) => {
      if (info.reason !== "destroyed") this.fail(`WebGPU device lost: ${info.message}`);
    });
    device.addEventListener("uncapturederror", (e) => this.fail(`WebGPU error: ${(e as GPUUncapturedErrorEvent).error.message}`));
  }

  private fail(reason: string): void {
    if (this.failed) return;
    this.failed = true;
    this.onFailure?.(reason);
  }

  resize(cssWidth: number, cssHeight: number, dpr: number): void {
    this.cssW = Math.max(1, cssWidth);
    this.cssH = Math.max(1, cssHeight);
    this.dpr = dpr;
    this.canvas.width = Math.max(1, Math.round(this.cssW * dpr));
    this.canvas.height = Math.max(1, Math.round(this.cssH * dpr));
  }

  private upload(key: string, data: ArrayBufferView, version: number, force = false): GPUBuffer {
    const bytes = Math.max(4, Math.ceil(data.byteLength / 4) * 4);
    let b = this.buffers.get(key);
    if (b && !force && b.version === version && b.bytes >= bytes) return b.buffer;
    if (!b || b.bytes < bytes) {
      b?.buffer.destroy();
      b = {
        buffer: this.device.createBuffer({ size: bytes, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST }),
        version: -1,
        bytes,
      };
      this.buffers.set(key, b);
    }
    const len = Math.floor(data.byteLength / 4) * 4;
    if (len) this.device.queue.writeBuffer(b.buffer, 0, data.buffer, data.byteOffset, len);
    if (len < data.byteLength) {
      const tail = new Uint8Array(4);
      tail.set(new Uint8Array(data.buffer, data.byteOffset + len, data.byteLength - len));
      this.device.queue.writeBuffer(b.buffer, len, tail);
    }
    b.version = version;
    return b.buffer;
  }

  private uniform(key: string, pipeline: GPURenderPipeline, data: Float32Array): GPUBindGroup {
    let u = this.uniforms.get(key);
    if (!u) {
      const buffer = this.device.createBuffer({ size: Math.max(16, data.byteLength), usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
      const group = this.device.createBindGroup({ layout: pipeline.getBindGroupLayout(0), entries: [{ binding: 0, resource: { buffer } }] });
      u = { buffer, group };
      this.uniforms.set(key, u);
    }
    this.device.queue.writeBuffer(u.buffer, 0, data);
    return u.group;
  }

  render(frame: FrameDraw): void {
    if (this.failed) return;
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [{ view: this.context.getCurrentTexture().createView(), clearValue: { r: 0, g: 0, b: 0, a: 0 }, loadOp: "clear", storeOp: "store" }],
    });
    const W = this.canvas.width;
    const H = this.canvas.height;
    const x0 = Math.min(W, Math.max(0, Math.round(frame.plot.x * this.dpr)));
    const y0 = Math.min(H, Math.max(0, Math.round(frame.plot.y * this.dpr)));
    const x1 = Math.min(W, Math.max(x0, Math.round((frame.plot.x + frame.plot.w) * this.dpr)));
    const y1 = Math.min(H, Math.max(y0, Math.round((frame.plot.y + frame.plot.h) * this.dpr)));
    pass.setScissorRect(x0, y0, x1 - x0, y1 - y0);
    for (const b of frame.bars) this.drawBars(pass, b, frame);
    frame.segments.forEach((s, i) => this.drawSegments(pass, s, i));
    for (const layer of frame.layers) this.drawMarks(pass, layer, frame);
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }

  private segmentVersion = 0;

  private drawSegments(pass: GPURenderPassEncoder, s: SegmentDraw, i: number): void {
    if (!s.count) return;
    pass.setPipeline(this.segments);
    const v = ++this.segmentVersion;
    pass.setVertexBuffer(0, this.upload(`segments${i}:coords`, s.coords.subarray(0, s.count * 4), v, true));
    pass.setVertexBuffer(1, this.upload(`segments${i}:colors`, s.colors.subarray(0, s.count * 4), v, true));
    pass.setBindGroup(0, this.uniform(`segments${i}`, this.segments, new Float32Array([this.cssW, this.cssH, s.width, 0])));
    pass.draw(6, s.count);
  }

  private drawBars(pass: GPURenderPassEncoder, layer: BarLayerDraw, frame: FrameDraw): void {
    if (!layer.count) return;
    const k = layer.key;
    pass.setPipeline(this.barsPipeline);
    pass.setVertexBuffer(0, this.upload(`${k}:x`, layer.x.data, layer.x.version));
    pass.setVertexBuffer(1, this.upload(`${k}:geom`, layer.geom.data, layer.geom.version));
    pass.setVertexBuffer(2, this.upload(`${k}:color`, layer.color.data, layer.color.version));
    pass.setVertexBuffer(3, this.upload(`${k}:flags`, layer.flags.data, layer.flags.version));
    const u = new Float32Array(24);
    u.set([this.cssW, this.cssH, 0, 0, frame.plot.x, frame.plot.y, frame.plot.w, frame.plot.h]);
    u.set([layer.offset, layer.scale, layer.laneTop, layer.laneHeight], 8);
    u.set([layer.fill, layer.maxBar, layer.fade ? 1 : 0, 0.5 + 0.5 / this.dpr], 12);
    u.set([...frame.background, 1], 16);
    u.set([...frame.selection, 1], 20);
    pass.setBindGroup(0, this.uniform(`${k}:u`, this.barsPipeline, u));
    pass.draw(6, layer.count);
  }

  private drawMarks(pass: GPURenderPassEncoder, layer: MarkLayerDraw, frame: FrameDraw): void {
    if (!layer.count) return;
    const k = layer.key;
    pass.setPipeline(this.marks);
    pass.setVertexBuffer(0, this.upload(`${k}:x`, layer.x.data, layer.x.version));
    pass.setVertexBuffer(1, this.upload(`${k}:lane`, layer.lane.data, layer.lane.version));
    pass.setVertexBuffer(2, this.upload(`${k}:dy`, layer.dy.data, layer.dy.version));
    pass.setVertexBuffer(3, this.upload(`${k}:size`, layer.size.data, layer.size.version));
    pass.setVertexBuffer(4, this.upload(`${k}:color`, layer.color.data, layer.color.version));
    pass.setVertexBuffer(5, this.upload(`${k}:sf`, layer.sf.data, layer.sf.version));
    const u = new Float32Array(24);
    u.set([this.cssW, this.cssH, frame.plot.x, frame.plot.y, layer.offset, layer.scale, layer.laneTop, layer.laneHeight]);
    u.set([...frame.background, 1], 8);
    u.set([...frame.selection, 1], 12);
    u.set([...frame.hover, 1], 16);
    u.set([layer.fade ? 1 : 0, 0.5 + 0.5 / this.dpr, 0, 0], 20);
    pass.setBindGroup(0, this.uniform(`${k}:u`, this.marks, u));
    pass.draw(6, layer.count);
  }

  async finish(): Promise<void> {
    await this.device.queue.onSubmittedWorkDone();
  }

  retain(keys: Set<string>): void {
    for (const [key, b] of [...this.buffers]) {
      const owner = key.slice(0, key.lastIndexOf(":"));
      if (!keys.has(owner) && !owner.startsWith("segments")) {
        b.buffer.destroy();
        this.buffers.delete(key);
      }
    }
    for (const [key, u] of [...this.uniforms]) {
      const owner = key.slice(0, key.lastIndexOf(":"));
      if (key.includes(":") && !keys.has(owner)) {
        u.buffer.destroy();
        this.uniforms.delete(key);
      }
    }
  }

  destroy(): void {
    this.retain(new Set());
    this.device.destroy();
  }
}
