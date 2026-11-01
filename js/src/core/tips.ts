// Tips for the toolbar's buttons: shown 0.15 s after the pointer comes to a button (at once
// when moving from one to the next) and when a button gets the keyboard's focus, which the
// browser's own tooltips (`title`, about a second, never on focus) do not. Greyed buttons
// have tips too: they say why the button is greyed. A button's tip is its `data-tip`.

/** How long the pointer rests on a button before its tip shows (ms). */
export const TIP_DELAY_MS = 150;

let ids = 0;

export class Tips {
  readonly el: HTMLDivElement;
  private current: HTMLElement | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly id = `atl-tip-${++ids}`;

  /** Tips for the `[data-tip]` elements in `area`, shown in `root` (positioned). */
  constructor(
    private readonly root: HTMLElement,
    private readonly area: HTMLElement,
  ) {
    this.el = document.createElement("div");
    this.el.className = "atl-button-tip";
    this.el.id = this.id;
    this.el.setAttribute("role", "tooltip");
    this.el.hidden = true;
    root.append(this.el);
    // pointer events, hit-tested by position: a disabled button gets none of its own
    area.addEventListener("pointermove", this.onMove);
    area.addEventListener("pointerleave", this.onLeave);
    area.addEventListener("pointerdown", this.onLeave);
    area.addEventListener("focusin", this.onFocus);
    area.addEventListener("focusout", this.onLeave);
  }

  private readonly onMove = (e: PointerEvent): void => {
    if (e.pointerType === "touch") return;
    const at = this.hit(e.clientX, e.clientY);
    if (at !== this.current) this.show(at);
  };

  private readonly onLeave = (): void => this.show(null);

  private readonly onFocus = (e: FocusEvent): void => {
    const t = (e.target as HTMLElement | null)?.closest<HTMLElement>("[data-tip]") ?? null;
    if (t && t.matches(":focus-visible")) this.show(t, 0);
  };

  /** The `[data-tip]` element under a point, also a disabled one. */
  private hit(x: number, y: number): HTMLElement | null {
    for (const t of this.area.querySelectorAll<HTMLElement>("[data-tip]")) {
      if (!t.offsetParent) continue; // hidden, or in a closed popover
      const r = t.getBoundingClientRect();
      if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return t;
    }
    return null;
  }

  /** Show the tip of `target` after `delay` (none when a tip is up already), or hide it. */
  show(target: HTMLElement | null, delay = TIP_DELAY_MS): void {
    clearTimeout(this.timer);
    this.current?.removeAttribute("aria-describedby");
    this.current = target;
    if (!target) {
      this.el.hidden = true;
      return;
    }
    const place = () => {
      if (this.current !== target || !target.isConnected) return;
      this.el.textContent = target.dataset.tip ?? "";
      this.el.hidden = false;
      target.setAttribute("aria-describedby", this.id);
      const root = this.root.getBoundingClientRect();
      const r = target.getBoundingClientRect();
      const w = this.el.offsetWidth;
      const left = Math.max(4, Math.min(root.width - w - 4, r.left - root.left + r.width / 2 - w / 2));
      this.el.style.left = `${Math.round(left)}px`;
      this.el.style.top = `${Math.round(r.bottom - root.top + 6)}px`;
    };
    if (!this.el.hidden || delay === 0) place();
    else this.timer = setTimeout(place, delay);
  }

  destroy(): void {
    clearTimeout(this.timer);
    this.area.removeEventListener("pointermove", this.onMove);
    this.area.removeEventListener("pointerleave", this.onLeave);
    this.area.removeEventListener("pointerdown", this.onLeave);
    this.area.removeEventListener("focusin", this.onFocus);
    this.area.removeEventListener("focusout", this.onLeave);
    this.el.remove();
  }
}
