#!/usr/bin/env python3
"""把 resources/icon.svg 渲染成 1024px PNG，并生成 .icns（macOS 应用图标）。

依赖：Pillow + svg.path（已装入 minihermes venv）
用法：python scripts/make_icon.py
产物：resources/icon.png (1024x1024) + resources/icon.icns
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw
from svg.path import parse_path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "resources" / "icon.svg"
PNG = ROOT / "resources" / "icon.png"
ICNS = ROOT / "resources" / "icon.icns"
SIZE = 1024

NS = "{http://www.w3.org/2000/svg}"


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hex_to_rgba(h, a=255):
    return (*hex_to_rgb(h), a)


def sample_path(d, steps=240):
    """SVG path → 多边形采样点（绝对坐标）"""
    p = parse_path(d)
    pts = []
    n = max(steps, int(p.length(error=1e-4)) * 2)
    for i in range(n + 1):
        pt = p.point(i / n)
        pts.append((pt.real, pt.imag))
    return pts


def parse_color(elem, attr, fallback):
    v = elem.get(attr)
    if not v:
        return fallback
    if v.startswith("#"):
        return hex_to_rgba(v)
    return fallback


def main():
    tree = ET.parse(SVG)
    root = tree.getroot()
    w = float(root.get("width", "1024"))
    h = float(root.get("height", "1024"))
    scale = SIZE / max(w, h)

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 预解析渐变
    grads = {}
    for g in root.iter(f"{NS}linearGradient"):
        gid = g.get("id")
        stops = []
        for s in g:
            if s.tag.endswith("stop"):
                off = float(s.get("offset", "0").rstrip("%")) / 100
                col = hex_to_rgb(s.get("stop-color", "#000"))
                op = float(s.get("stop-opacity", "1"))
                stops.append((off, (*col, int(op * 255))))
        grads[gid] = stops

    def fill_for(elem):
        fill = elem.get("fill")
        if fill and fill.startswith("url(#"):
            gid = fill[5:-1]
            stops = grads.get(gid, [(0, (0, 0, 0, 255)), (1, (0, 0, 0, 255))])
            return ("grad", stops)
        return ("solid", parse_color(elem, "fill", (0, 0, 0, 255)))

    def paint_poly(pts, fill_spec, opacity=1.0):
        if fill_spec[0] == "grad":
            stops = fill_spec[1]
            # 垂直渐变（按 y 从 min 到 max）
            ys = [p[1] for p in pts]
            y0, y1 = min(ys), max(ys)
            if y1 <= y0:
                y1 = y0 + 1
            # 对每个 y 画水平线（用多边形扫描太复杂，改用 mask 近似：
            # 先画纯色占位，再叠加渐变线）
            base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            bd = ImageDraw.Draw(base)
            bd.polygon(pts, fill=(255, 255, 255, 255))
            mask = base.split()[3]
            # 渐变填充：逐行
            grad_img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            gd = ImageDraw.Draw(grad_img)
            def grad_color(y):
                t = (y - y0) / (y1 - y0)
                t = max(0.0, min(1.0, t))
                for i in range(len(stops) - 1):
                    o0, c0 = stops[i]
                    o1, c1 = stops[i + 1]
                    if o0 <= t <= o1:
                        tt = (t - o0) / (o1 - o0) if o1 != o0 else 0
                        return tuple(int(c0[k] + (c1[k] - c0[k]) * tt) for k in range(4))
                return stops[-1][1]
            for y in range(y0, y1):
                gd.line([(0, y), (SIZE, y)], fill=grad_color(y))
            img.paste(grad_img, (0, 0), mask)
        else:
            color = fill_spec[1]
            if opacity < 1.0:
                color = (*color[:3], int(color[3] * opacity))
            draw.polygon(pts, fill=color)

    # 遍历元素（保持顺序）
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "rect":
            x = float(elem.get("x", 0)) * scale
            y = float(elem.get("y", 0)) * scale
            ww = float(elem.get("width", 0)) * scale
            hh = float(elem.get("height", 0)) * scale
            rx = float(elem.get("rx", 0)) * scale
            fill_spec = fill_for(elem)
            if fill_spec[0] == "grad":
                # 圆角矩形渐变：画 mask
                base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
                bd = ImageDraw.Draw(base)
                bd.rounded_rectangle([x, y, x + ww, y + hh], radius=rx, fill=(255, 255, 255, 255))
                mask = base.split()[3]
                stops = fill_spec[1]
                grad_img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
                gd = ImageDraw.Draw(grad_img)
                y0, y1 = y, y + hh
                def gc(ty):
                    ty = max(0.0, min(1.0, ty))
                    for i in range(len(stops) - 1):
                        o0, c0 = stops[i]
                        o1, c1 = stops[i + 1]
                        if o0 <= ty <= o1:
                            tt = (ty - o0) / (o1 - o0) if o1 != o0 else 0
                            return tuple(int(c0[k] + (c1[k] - c0[k]) * tt) for k in range(4))
                    return stops[-1][1]
                for yy in range(int(y0), int(y1)):
                    gd.line([(0, yy), (SIZE, yy)], fill=gc((yy - y0) / (y1 - y0)))
                img.paste(grad_img, (0, 0), mask)
            else:
                draw.rounded_rectangle([x, y, x + ww, y + hh], radius=rx, fill=fill_spec[1])
        elif tag == "circle":
            cx = float(elem.get("cx", 0)) * scale
            cy = float(elem.get("cy", 0)) * scale
            r = float(elem.get("r", 0)) * scale
            fill_spec = fill_for(elem)
            if fill_spec[0] == "grad":
                stops = fill_spec[1]
                c0, c1 = stops[0][1], stops[-1][1]
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c0)
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill_spec[1])
        elif tag == "ellipse":
            cx = float(elem.get("cx", 0)) * scale
            cy = float(elem.get("cy", 0)) * scale
            rx = float(elem.get("rx", 0)) * scale
            ry = float(elem.get("ry", 0)) * scale
            col = parse_color(elem, "fill", (0, 0, 0, 255))
            op = float(elem.get("opacity", "1"))
            draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                         fill=(*col[:3], int(col[3] * op)))
        elif tag == "path":
            d = elem.get("d")
            if not d:
                continue
            pts = sample_path(d)
            pts = [(x * scale, y * scale) for x, y in pts]
            fill_spec = fill_for(elem)
            op = float(elem.get("opacity", "1"))
            stroke = elem.get("stroke")
            if stroke:
                sw = float(elem.get("stroke-width", "1")) * scale
                sc = hex_to_rgba(stroke, int(float(elem.get("stroke-opacity", "1")) * 255))
                # 先填充（如果有 fill 且非 none）
                if elem.get("fill") and elem.get("fill") != "none" and fill_spec[0] == "solid":
                    draw.polygon(pts, fill=fill_spec[1])
                # 描边：连线
                for i in range(len(pts) - 1):
                    draw.line([pts[i], pts[i + 1]], fill=sc, width=int(max(1, sw)))
            else:
                paint_poly(pts, fill_spec, op)

    # 输出 PNG
    img = img.convert("RGBA")
    img.save(PNG, "PNG")
    print(f"[ok] PNG: {PNG} ({PNG.stat().st_size // 1024}KB)")

    # 生成 iconset + icns
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "icon.iconset"
        iconset.mkdir()
        sizes = {
            "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
            "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
            "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
            "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
            "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
        }
        for name, s in sizes.items():
            img.resize((s, s), Image.LANCZOS).save(iconset / name, "PNG")
        r = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print("[err] iconutil:", r.stderr, file=sys.stderr)
            sys.exit(1)
    print(f"[ok] ICNS: {ICNS} ({ICNS.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
