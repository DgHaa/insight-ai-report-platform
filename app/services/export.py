"""报告导出服务：支持 markdown / docx / pdf 三种格式。

- PDF 注册 reportlab 内置中文字体（STSong-Light），否则中文无法渲染；
- 解析 Markdown 结构（标题/列表/表格/代码块/引用/加粗），
  三种格式统一走同一套块解析器；
- 每个模块强制插入模块标题，不依赖模型自觉输出标题。
"""
import io
import re

from app.core.config import settings
from app.core.exceptions import ParamError

# ==================== PDF 中文字体 ====================
# reportlab 默认 Helvetica 无法编码中文，必须注册 CJK 字体。
# STSong-Light 是 reportlab 内置 CID 字体，无需额外字体文件。
from reportlab.pdfbase import pdfmetrics

_PDF_CJK_FONT = "STSong-Light"
_cjk_font_ready = False


def _ensure_cjk_font() -> str | None:
    """注册 PDF 中文字体（幂等）。成功返回字体名，失败返回 None（退回默认字体）。"""
    global _cjk_font_ready
    if _cjk_font_ready:
        return _PDF_CJK_FONT
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        pdfmetrics.registerFont(UnicodeCIDFont(_PDF_CJK_FONT))
        # <b>/<i> 内联标签需要字体族映射；STSong 无粗体变体，映射到自身
        registerFontFamily(
            _PDF_CJK_FONT,
            normal=_PDF_CJK_FONT,
            bold=_PDF_CJK_FONT,
            italic=_PDF_CJK_FONT,
            boldItalic=_PDF_CJK_FONT,
        )
        _cjk_font_ready = True
        return _PDF_CJK_FONT
    except Exception:  # noqa: BLE001
        return None


# ==================== Markdown 块解析 ====================
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_ORDERED = re.compile(r"^(\d+)[.、)]\s+(.*)$")


def _split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_blocks(text: str) -> list[dict]:
    """把 Markdown 文本解析为结构化块，供 docx / pdf 渲染。

    支持的块类型：
    - heading  {level, text}
    - paragraph {text}
    - list_item {ordered, text}
    - table    {rows: [[c,...],...]}（首行为表头）
    - code     {text}
    - quote    {text}
    """
    blocks: list[dict] = []
    lines = (text or "").splitlines()
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append({"type": "paragraph", "text": "\n".join(para)})
            para.clear()

    i = 0
    in_code = False
    code_lines: list[str] = []
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                blocks.append({"type": "code", "text": "\n".join(code_lines)})
                code_lines.clear()
                in_code = False
            else:
                flush()
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        m = _HEADING.match(s)
        if m:
            flush()
            blocks.append({"type": "heading", "level": len(m.group(1)), "text": m.group(2).strip()})
            i += 1
            continue
        # 表格：当前行是 | 开头，下一行是分隔行
        if s.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            rows = [_split_table_row(s)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_table_row(lines[i]))
                i += 1
            if rows and rows[-1] and all(not c for c in rows[-1]):
                rows.pop()
            blocks.append({"type": "table", "rows": rows})
            continue
        m = _BULLET.match(s)
        if m:
            flush()
            blocks.append({"type": "list_item", "ordered": False, "text": m.group(1)})
            i += 1
            continue
        m = _ORDERED.match(s)
        if m:
            flush()
            blocks.append({"type": "list_item", "ordered": True, "text": m.group(2)})
            i += 1
            continue
        if s.startswith(">"):
            flush()
            blocks.append({"type": "quote", "text": s.lstrip(">").strip()})
            i += 1
            continue
        para.append(s)
        i += 1
    flush()
    if in_code and code_lines:
        blocks.append({"type": "code", "text": "\n".join(code_lines)})
    return blocks


def _parse_inline(text: str) -> list[tuple[str, bool]]:
    """按 **粗体** 拆分为 (文本, 是否加粗) 片段。"""
    segments: list[tuple[str, bool]] = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text or "")):
        if part:
            segments.append((part, i % 2 == 1))
    return segments or [("", False)]


def _module_markdown(title: str, content: str) -> str:
    """模块内容 + 强制模块标题（若模型已输出同名标题则不重复）。"""
    title = (title or "").strip()
    content = (content or "").strip()
    if not title:
        return content
    first = next((l.strip() for l in content.splitlines() if l.strip()), "")
    m = _HEADING.match(first) if first else None
    if m and title in m.group(2):
        return content
    return f"## {title}\n\n{content}" if content else f"## {title}"


def _chart_type_cn(chart_type: str | None) -> str:
    return {"bar": "柱状图", "line": "折线图", "pie": "饼图"}.get(chart_type or "", chart_type or "")


def _data_points_md(data_points: list | None) -> str:
    """把数据点渲染为 Markdown 列表（空则空串）。"""
    if not data_points:
        return ""
    trend_map = {"up": "↑", "down": "↓", "flat": "→"}
    lines = ["**关键数据点**", ""]
    for dp in data_points:
        val = f"{dp.get('value', '')}{dp.get('unit', '')}".strip()
        trend = trend_map.get(dp.get("trend", ""), "")
        line = f"- **{dp.get('label', '')}**：{val} {trend}".rstrip()
        if dp.get("note"):
            line += f" — {dp['note']}"
        lines.append(line)
    return "\n".join(lines)


def _charts_md(charts: list | None) -> str:
    """把图表规格渲染为 Markdown 列表（空则空串）。"""
    if not charts:
        return ""
    lines = ["**图表**", ""]
    for ch in charts:
        line = f"- {ch.get('title', '图表')}（{_chart_type_cn(ch.get('type'))}）"
        if ch.get("caption"):
            line += f"：{ch['caption']}"
        lines.append(line)
    return "\n".join(lines)


def render_markdown(title: str, content: dict) -> str:
    """将版本内容（JSONB）渲染为 Markdown 文本。"""
    parts = [f"# {title}", ""]
    summary = content.get("summary")
    if summary:
        parts.append(str(summary))
        parts.append("")
    for module in content.get("modules", []):
        module_content = module.get("content")
        if isinstance(module_content, str):
            parts.append(_module_markdown(module.get("module_title", ""), module_content))
            parts.append("")
        elif isinstance(module_content, dict):
            parts.append(_module_markdown(module.get("module_title", ""), str(module_content.get("text", ""))))
            parts.append("")
        # 结构化辅助组件：数据点 + 图表（保证导出不丢信息）
        extra = _data_points_md(module.get("data_points")) + "\n" + _charts_md(module.get("charts"))
        if extra.strip():
            parts.append(extra.strip())
            parts.append("")
    return "\n".join(parts).strip()


def _safe_filename(title: str, version: int, fmt: str) -> str:
    """生成安全的导出文件名。"""
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", title).strip("_") or "report"
    return f"{safe}_v{version}.{fmt}"


def _hex_rgb(color: str | None) -> tuple[int, int, int] | None:
    """解析 #RRGGBB 颜色字符串为 RGB 元组。"""
    if not color or not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
        return None
    try:
        return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except ValueError:
        return None


def export_markdown(title: str, content: dict, version: int) -> tuple[bytes, str]:
    md = render_markdown(title, content)
    return md.encode("utf-8"), _safe_filename(title, version, "md")


# ==================== DOCX ====================


def _add_data_points_docx(document, data_points: list | None, primary) -> None:
    """在 DOCX 中把数据点渲染为表格（无数据点时跳过）。"""
    if not data_points:
        return
    document.add_paragraph().add_run("关键数据点").bold = True
    table = document.add_table(rows=len(data_points) + 1, cols=3)
    table.style = "Table Grid"
    headers = ["指标", "数值", "说明"]
    for c, h in enumerate(headers):
        cell = table.rows[0].cells[c]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        if primary:
            run.font.color.rgb = RGBColor(*primary)
    for i, dp in enumerate(data_points, start=1):
        cells = table.rows[i].cells
        cells[0].text = str(dp.get("label", ""))
        cells[1].text = f"{dp.get('value', '')}{dp.get('unit', '')}".strip()
        cells[2].text = str(dp.get("note", ""))
    document.add_paragraph()


def export_docx(
    title: str, content: dict, version: int, style_config: dict | None = None
) -> tuple[bytes, str]:
    """使用 python-docx 生成 Word 文档（支持标题/列表/表格/粗体，应用风格主色/字号）。"""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except ImportError as exc:  # pragma: no cover
        raise ParamError("导出 docx 需要安装 python-docx") from exc

    primary = _hex_rgb(style_config.get("primary_color")) if style_config else None
    body_size = (
        int(style_config.get("body_font_size")) if style_config and style_config.get("body_font_size") else 0
    )

    document = Document()

    def _add_runs(paragraph, text: str, force_color=False):
        for seg, bold in _parse_inline(text):
            run = paragraph.add_run(seg)
            run.bold = bold or force_color and paragraph.style.name.startswith("Heading")
            if force_color and primary:
                run.font.color.rgb = RGBColor(*primary)

    title_para = document.add_heading(title, level=0)
    _add_runs(title_para, title, force_color=True)
    if body_size:
        document.styles["Normal"].font.size = Pt(body_size)

    summary = content.get("summary")
    if summary:
        _add_runs(document.add_paragraph(), str(summary))

    for module in content.get("modules", []):
        mc = module.get("content", "")
        if isinstance(mc, dict):
            mc = mc.get("text", "")
        module_md = _module_markdown(module.get("module_title", ""), str(mc))
        for block in parse_blocks(module_md):
            btype = block["type"]
            if btype == "heading":
                level = max(1, min(block["level"], 4))
                para = document.add_heading("", level=level)
                _add_runs(para, block["text"], force_color=True)
            elif btype == "list_item":
                style = "List Number" if block["ordered"] else "List Bullet"
                para = document.add_paragraph(style=style)
                _add_runs(para, block["text"])
            elif btype == "table":
                rows = block["rows"]
                if rows:
                    table = document.add_table(rows=len(rows), cols=len(rows[0]))
                    table.style = "Table Grid"
                    for r, row in enumerate(rows):
                        for c, cell_text in enumerate(row):
                            if c < len(table.rows[r].cells):
                                cell = table.rows[r].cells[c]
                                cell.text = ""
                                p = cell.paragraphs[0]
                                if r == 0:
                                    _add_runs(p, cell_text)
                                    for run in p.runs:
                                        run.bold = True
                                        if primary:
                                            run.font.color.rgb = RGBColor(*primary)
                                else:
                                    _add_runs(p, cell_text)
                    document.add_paragraph()
            elif btype == "code":
                para = document.add_paragraph()
                run = para.add_run(block["text"])
                run.font.name = "Consolas"
                run.font.size = Pt(max(8, (body_size or 11) - 1))
            elif btype == "quote":
                para = document.add_paragraph(style="Intense Quote")
                _add_runs(para, block["text"])
            else:
                para = document.add_paragraph()
                _add_runs(para, block["text"])

        # 结构化辅助组件：数据点表 + 图表说明（排版底线，保证结构化模块导出不丢信息）
        _add_data_points_docx(document, module.get("data_points"), primary)
        for ch in module.get("charts") or []:
            para = document.add_paragraph()
            run = para.add_run(f"图表：{ch.get('title', '图表')}（{_chart_type_cn(ch.get('type'))}）")
            run.bold = True
            if primary:
                run.font.color.rgb = RGBColor(*primary)
            if ch.get("caption"):
                document.add_paragraph(ch["caption"])

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue(), _safe_filename(title, version, "docx")


# ==================== PDF ====================

def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _inline_xml(text: str) -> str:
    """转义并把 **粗体** 转为 reportlab 内联 <b> 标签。"""
    out = []
    for seg, bold in _parse_inline(text):
        esc = _xml_escape(seg).replace("\n", "<br/>")
        out.append(f"<b>{esc}</b>" if bold else esc)
    return "".join(out)


def export_pdf(
    title: str, content: dict, version: int, style_config: dict | None = None
) -> tuple[bytes, str]:
    """使用 reportlab 生成 PDF（中文字体 + 标题/列表/表格，应用风格主色/字号）。"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover
        raise ParamError("导出 pdf 需要安装 reportlab") from exc

    # 中文字体：未注册成功时退回默认（此时中文将无法渲染）
    font = _ensure_cjk_font()

    primary_hex = style_config.get("primary_color") if style_config else None
    body_size = (
        int(style_config.get("body_font_size")) if style_config and style_config.get("body_font_size") else 0
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=title, rightMargin=48, leftMargin=48
    )
    styles = getSampleStyleSheet()

    def _mk(name: str, parent: str, **kw) -> ParagraphStyle:
        s = ParagraphStyle(name, parent=styles[parent], **kw)
        # 未显式指定字体（如代码块用 Courier）时才应用中文字体
        if font and "fontName" not in kw:
            s.fontName = font
        return s

    h1_style = _mk("H1", "Heading1", spaceAfter=12)
    h2_style = _mk("H2", "Heading2")
    h3_style = _mk("H3", "Heading3")
    h4_style = _mk("H4", "Heading4")
    body_style = _mk("Body", "BodyText", spaceAfter=6)
    quote_style = _mk("Quote", "BodyText", spaceAfter=6, leftIndent=12, textColor=colors.grey)
    bullet_style = _mk("Bullet", "BodyText", spaceAfter=2, leftIndent=14, bulletIndent=4)
    code_style = _mk("Code", "BodyText", spaceAfter=6, fontName="Courier", fontSize=8.5)
    if body_size:
        body_style.fontSize = body_size
        bullet_style.fontSize = body_size

    if primary_hex:
        for s in (h1_style, h2_style, h3_style, h4_style):
            s.textColor = HexColor(primary_hex)

    story = [Paragraph(_xml_escape(title), h1_style), Spacer(1, 6)]
    summary = content.get("summary")
    if summary:
        story.append(Paragraph(_inline_xml(str(summary)), body_style))
        story.append(Spacer(1, 6))

    def _add_blocks(markdown_text: str) -> None:
        for block in parse_blocks(markdown_text):
            btype = block["type"]
            if btype == "heading":
                level = max(1, min(block["level"], 4))
                style = {1: h2_style, 2: h3_style, 3: h4_style, 4: h4_style}[level]
                story.append(Paragraph(_xml_escape(block["text"]), style))
            elif btype == "list_item":
                marker = "• " if not block["ordered"] else ""
                story.append(Paragraph(marker + _inline_xml(block["text"]), bullet_style))
            elif btype == "table":
                rows = block["rows"]
                if rows:
                    data = [
                        [Paragraph(_inline_xml(c), body_style) for c in row]
                        for row in rows
                    ]
                    ncols = max(len(r) for r in rows)
                    t = Table(data, colWidths=[(A4[0] - 96) / ncols] * ncols, repeatRows=1)
                    # 表头背景：主色的浅色版（与白底混合 88%），未配置主色时用浅灰
                    rgb = _hex_rgb(primary_hex) if primary_hex else None
                    if rgb:
                        header_bg = colors.Color(
                            rgb[0] / 255 * 0.12 + 0.88,
                            rgb[1] / 255 * 0.12 + 0.88,
                            rgb[2] / 255 * 0.12 + 0.88,
                        )
                    else:
                        header_bg = colors.HexColor("#EEF2F7")
                    t.setStyle(
                        TableStyle(
                            [
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(primary_hex or "#CCCCCC")),
                                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ]
                        )
                    )
                    story.append(t)
                    story.append(Spacer(1, 6))
            elif btype == "code":
                for line in block["text"].splitlines():
                    story.append(Paragraph(_xml_escape(line.replace(" ", "&nbsp;")), code_style))
            elif btype == "quote":
                story.append(Paragraph(_inline_xml(block["text"]), quote_style))
            else:
                story.append(Paragraph(_inline_xml(block["text"]), body_style))

    for module in content.get("modules", []):
        mc = module.get("content", "")
        if isinstance(mc, dict):
            mc = mc.get("text", "")
        module_md = _module_markdown(module.get("module_title", ""), str(mc))
        _add_blocks(module_md)

        # 结构化辅助组件：数据点表 + 图表说明
        dps = module.get("data_points") or []
        if dps:
            story.append(Paragraph("<b>关键数据点</b>", body_style))
            rows = [["指标", "数值", "说明"]] + [
                [
                    str(dp.get("label", "")),
                    f"{dp.get('value', '')}{dp.get('unit', '')}".strip(),
                    str(dp.get("note", "")),
                ]
                for dp in dps
            ]
            ncols = 3
            t = Table(rows, colWidths=[(A4[0] - 96) / ncols] * ncols, repeatRows=1)
            rgb = _hex_rgb(primary_hex) if primary_hex else None
            if rgb:
                header_bg = colors.Color(
                    rgb[0] / 255 * 0.12 + 0.88,
                    rgb[1] / 255 * 0.12 + 0.88,
                    rgb[2] / 255 * 0.12 + 0.88,
                )
            else:
                header_bg = colors.HexColor("#EEF2F7")
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(primary_hex or "#CCCCCC")),
                        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 6))
        for ch in module.get("charts") or []:
            caption = f"：{_inline_xml(ch['caption'])}" if ch.get("caption") else ""
            story.append(
                Paragraph(
                    f"<b>图表：{_xml_escape(ch.get('title', '图表'))}</b>"
                    f"（{_chart_type_cn(ch.get('type'))}）{caption}",
                    body_style,
                )
            )
            story.append(Spacer(1, 6))

    doc.build(story)
    return buf.getvalue(), _safe_filename(title, version, "pdf")


MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


async def export_report(
    title: str, content: dict, version: int, fmt: str, style_config: dict | None = None
) -> tuple[bytes, str, str]:
    """导出报告，返回 (文件内容, 文件名, media_type)。"""
    if fmt not in MEDIA_TYPES:
        raise ParamError(f"不支持的导出格式: {fmt}（仅支持 pdf/docx/md）")
    if fmt == "md":
        payload, filename = export_markdown(title, content, version)
    elif fmt == "docx":
        payload, filename = export_docx(title, content, version, style_config)
    else:
        payload, filename = export_pdf(title, content, version, style_config)
    return payload, filename, MEDIA_TYPES[fmt]
