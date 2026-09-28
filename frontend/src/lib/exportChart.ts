export async function chartToPng(container: HTMLElement, filename: string): Promise<boolean> {
  const svg = container.querySelector("svg.recharts-surface") as SVGSVGElement | null;
  if (!svg) return false;
  const { width, height } = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const styles = getComputedStyle(document.documentElement);
  const resolve = (value: string) => value.replace(/var\((--[\w-]+)\)/g, (_, name) => styles.getPropertyValue(name).trim());
  clone.querySelectorAll<SVGElement>("*").forEach((el) => {
    for (const attr of ["fill", "stroke", "stop-color"]) {
      const v = el.getAttribute(attr);
      if (v?.includes("var(")) el.setAttribute(attr, resolve(v));
    }
  });
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const background = styles.getPropertyValue("--panel").trim() || "#ffffff";
  const source = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([source], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = new Image();
    await new Promise<void>((resolveLoad, reject) => {
      image.onload = () => resolveLoad();
      image.onerror = () => reject(new Error("render failed"));
      image.src = url;
    });
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return false;
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(image, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
    if (!blob) return false;
    downloadBlob(blob, filename);
    return true;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "result";
}
