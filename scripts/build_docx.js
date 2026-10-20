// Renders a block-spec JSON (from prep_report.py) into a .docx
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, BorderStyle, ImageRun, Header, Footer, PageNumber, HeadingLevel, LevelFormat,
} = require("docx");

const [, , specPath, outPath] = process.argv;
const blocks = JSON.parse(fs.readFileSync(specPath, "utf8"));

const FONT = "Calibri";
const ACCENT = "1F3B57";
const MUTED = "6B7280";
const CONTENT_W = 9360;

const border = { style: BorderStyle.SINGLE, size: 4, color: "C8CDD4" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function run(text, opts = {}) {
  return new TextRun({ text: String(text), font: FONT, ...opts });
}

function cell(c, width, isHeader) {
  const obj = typeof c === "object" && c !== null ? c : { text: c };
  const fill = isHeader ? ACCENT : obj.fill || undefined;
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({
      spacing: { after: 0 },
      children: [run(obj.text, { size: 17, bold: isHeader || obj.bold, color: isHeader ? "FFFFFF" : undefined })],
    })],
  });
}

function table(b) {
  const total = b.widths.reduce((a, x) => a + x, 0);
  const widths = total > CONTENT_W ? b.widths.map((w) => Math.floor((w * CONTENT_W) / total)) : b.widths;
  const sum = widths.reduce((a, x) => a + x, 0);
  const rows = [
    new TableRow({ tableHeader: true, cantSplit: true, children: b.header.map((h, i) => cell(h, widths[i], true)) }),
    ...b.rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, widths[i], false)) })),
  ];
  return [
    new Table({ width: { size: sum, type: WidthType.DXA }, columnWidths: widths, rows }),
    new Paragraph({ spacing: { after: 120 }, children: [] }),
  ];
}

function imageCell(b) {
  const h = Math.round(b.w);
  return new TableCell({
    borders: noBorders,
    width: { size: CONTENT_W / 2, type: WidthType.DXA },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 40 },
        children: [new ImageRun({ type: "png", data: fs.readFileSync(b.path), transformation: { width: b.w, height: h },
          altText: { title: "diagram", description: b.caption || "diagram", name: "diagram" } })],
      }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 },
        children: [run(b.caption || "", { size: 16, italics: true, color: MUTED })] }),
    ],
  });
}

const children = [];
for (let i = 0; i < blocks.length; i++) {
  const b = blocks[i];
  switch (b.t) {
    case "title":
      children.push(new Paragraph({ spacing: { before: 2400, after: 200 }, alignment: AlignmentType.CENTER,
        children: [run(b.text, { size: 60, bold: true, color: ACCENT })] }));
      children.push(new Paragraph({ spacing: { after: 600 }, alignment: AlignmentType.CENTER,
        children: [run(b.sub, { size: 30, color: MUTED })] }));
      break;
    case "h1":
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
        spacing: { before: 0, after: 200 }, children: [run(b.text, { size: 34, bold: true, color: ACCENT })] }));
      break;
    case "h2":
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true,
        spacing: { before: 280, after: 120 }, children: [run(b.text, { size: 26, bold: true, color: ACCENT })] }));
      break;
    case "h3":
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_3, keepNext: true,
        spacing: { before: 200, after: 100 }, children: [run(b.text, { size: 22, bold: true })] }));
      break;
    case "p":
      children.push(new Paragraph({ spacing: { after: 120 }, children: [run(b.text, { size: 21 })] }));
      break;
    case "note":
      children.push(new Paragraph({ spacing: { after: 160 }, children: [run(b.text, { size: 17, italics: true, color: MUTED })] }));
      break;
    case "bullets":
      for (const it of b.items) {
        children.push(new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 60 },
          children: [run(it, { size: 21 })] }));
      }
      break;
    case "table":
      children.push(...table(b));
      break;
    case "image": {
      const pair = [b];
      if (blocks[i + 1] && blocks[i + 1].t === "image") { pair.push(blocks[i + 1]); i++; }
      const cells = pair.map(imageCell);
      if (cells.length === 1) {
        cells.push(new TableCell({ borders: noBorders, width: { size: CONTENT_W / 2, type: WidthType.DXA }, children: [new Paragraph("")] }));
      }
      children.push(new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W / 2, CONTENT_W / 2],
        rows: [new TableRow({ cantSplit: true, children: cells })] }));
      children.push(new Paragraph({ spacing: { after: 80 }, children: [] }));
      break;
    }
    case "break":
      break;
  }
}

const doc = new Document({
  creator: "Opponent Scout",
  title: "Подготовка к турниру",
  styles: { default: { document: { run: { font: FONT, size: 21 } } } },
  numbering: { config: [{ reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1273, right: 1273 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [run("Подготовка к турниру", { size: 16, color: MUTED })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [run("Стр. ", { size: 16, color: MUTED }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED, font: FONT })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(outPath, buf); console.log("written", outPath); });
