// Content-addressed buffer store fed by chunked "put" messages from Python.
// Transport-agnostic: the caller supplies how "need" requests are sent.

export interface PutMessage {
  type: "put";
  id: string;
  chunk: number;
  chunks: number;
  /** Byte offset of this chunk in the full buffer. */
  offset: number;
  byteLength: number;
  /** Python time.time() when sending started, in seconds. */
  t_send: number;
  /** Served as a file instead (marimo): fetch this URL; `file` names it for Python. */
  url?: string;
  file?: string;
}

export interface TransferStat {
  bytes: number;
  /** Epoch milliseconds. */
  sentAt: number;
  receivedAt: number;
}

interface Partial {
  target: Uint8Array;
  received: number;
  chunks: number;
  sentAt: number;
}

/** Quiet time (ms) with requests open after which the store counts as stalled. */
export const STALL_MS = 4000;

export class BufferStore {
  private readonly buffers = new Map<string, ArrayBuffer>();
  private readonly partial = new Map<string, Partial>();
  private readonly waiters = new Map<string, Array<() => void>>();
  private readonly requested = new Set<string>();
  readonly stats = new Map<string, TransferStat>();
  /** A request got no answer for STALL_MS: Python is gone (e.g. its kernel restarted). */
  stalled = false;
  /** Some data came from Python (not only embedded in the widget state). */
  received = false;
  /** Some data came embedded in the widget state (Timeline embed). */
  embedded = false;
  /** Called when `stalled` changes. */
  onStall: ((stalled: boolean) => void) | null = null;
  private lastActivity = 0;
  private stallTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly request: (ids: string[]) => void) {}

  has(id: string): boolean {
    return this.buffers.has(id);
  }

  get(id: string): ArrayBuffer {
    const b = this.buffers.get(id);
    if (!b) throw new Error(`buffer ${id} not loaded`);
    return b;
  }

  /** Resolve once every id is present, requesting the missing ones once. */
  async ensure(ids: string[]): Promise<void> {
    const missing = ids.filter((id) => !this.buffers.has(id));
    const toRequest = missing.filter((id) => !this.requested.has(id));
    toRequest.forEach((id) => this.requested.add(id));
    const done = Promise.all(missing.map((id) => new Promise<void>((resolve) => this.wait(id, resolve))));
    if (toRequest.length) {
      this.lastActivity = Date.now();
      try {
        this.request(toRequest);
      } catch (err) {
        // no way to Python at all (JupyterLab throws "Cannot send" after a kernel restart):
        // stalled now; forget the ids so that a later attempt asks again
        console.warn("[anytimeline] cannot ask Python for data:", err);
        toRequest.forEach((id) => this.requested.delete(id));
        this.setStalled(true);
        await done;
        return;
      }
      this.watch();
    }
    await done;
  }

  /**
   * Check, STALL_MS after the last request or arrival, that the answers are coming. Python
   * answers at once, and a large buffer arrives in chunks, so a quiet spell with requests
   * open means nobody answers: a kernel that restarted, or no kernel at all.
   */
  private watch(): void {
    clearTimeout(this.stallTimer);
    if (!this.requested.size) return;
    const quiet = Date.now() - this.lastActivity;
    if (quiet >= STALL_MS) {
      this.setStalled(true);
      return;
    }
    this.stallTimer = setTimeout(() => this.watch(), STALL_MS - quiet);
  }

  private setStalled(stalled: boolean): void {
    if (stalled === this.stalled) return;
    this.stalled = stalled;
    this.onStall?.(stalled);
  }

  /**
   * Keep only these buffers (those of the scene shown): the rest, half-received ones and
   * open requests are dropped, and whoever waits for a dropped one is let go (it checks
   * `has` and draws what it has).
   */
  retain(ids: Set<string>): void {
    for (const id of [...this.buffers.keys()]) if (!ids.has(id)) this.buffers.delete(id);
    for (const id of [...this.stats.keys()]) if (!ids.has(id)) this.stats.delete(id);
    for (const id of [...this.partial.keys()]) if (!ids.has(id)) this.partial.delete(id);
    for (const id of [...this.requested]) if (!ids.has(id)) this.requested.delete(id);
    for (const id of [...this.waiters.keys()]) if (!ids.has(id)) this.release(id);
    this.watch();
  }

  /** Python has no buffer ``id`` (it was freed): stop waiting, ask again if it comes back. */
  missing(id: string): void {
    this.requested.delete(id);
    this.partial.delete(id);
    this.release(id);
    this.watch();
  }

  private release(id: string): void {
    const ws = this.waiters.get(id) ?? [];
    this.waiters.delete(id);
    ws.forEach((resolve) => resolve());
  }

  /** Add a whole buffer that arrived another way (e.g. embedded in the widget state). */
  add(id: string, data: DataView | ArrayBuffer | Uint8Array): void {
    if (this.buffers.has(id)) return;
    this.embedded = true;
    this.requested.delete(id);
    this.buffers.set(id, copyBytes(data));
    const ws = this.waiters.get(id) ?? [];
    this.waiters.delete(id);
    ws.forEach((resolve) => resolve());
  }

  receive(msg: PutMessage, chunk: DataView | ArrayBuffer | Uint8Array): void {
    const bytes =
      chunk instanceof Uint8Array
        ? chunk
        : chunk instanceof ArrayBuffer
          ? new Uint8Array(chunk)
          : new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength);
    this.received = true;
    this.lastActivity = Date.now();
    this.setStalled(false);
    let p = this.partial.get(msg.id);
    if (!p) {
      p = { target: new Uint8Array(msg.byteLength), received: 0, chunks: msg.chunks, sentAt: msg.t_send * 1000 };
      this.partial.set(msg.id, p);
    }
    p.target.set(bytes, msg.offset);
    p.received += 1;
    if (p.received < p.chunks) return;
    this.partial.delete(msg.id);
    this.requested.delete(msg.id);
    this.buffers.set(msg.id, p.target.buffer as ArrayBuffer);
    this.stats.set(msg.id, {
      bytes: msg.byteLength,
      sentAt: p.sentAt,
      receivedAt: performance.timeOrigin + performance.now(),
    });
    const ws = this.waiters.get(msg.id) ?? [];
    this.waiters.delete(msg.id);
    ws.forEach((resolve) => resolve());
    this.watch(); // other requests may still be open
  }

  private wait(id: string, resolve: () => void): void {
    const list = this.waiters.get(id) ?? [];
    list.push(resolve);
    this.waiters.set(id, list);
  }
}

/** The bytes of a view as an ArrayBuffer of their own (a view may share a larger buffer). */
function copyBytes(data: DataView | ArrayBuffer | Uint8Array): ArrayBuffer {
  if (data instanceof ArrayBuffer) return data.slice(0);
  return new Uint8Array(data.buffer, data.byteOffset, data.byteLength).slice().buffer as ArrayBuffer;
}
