// Общее оформление программных документов ЕСПД (ЛУ, ТЛ, текст, ЛРИ)
const fs = require('fs');
const D = require('docx');
const {
  Paragraph, TextRun, Table, TableRow, TableCell, WidthType, AlignmentType, BorderStyle,
  Header, PageNumber, TextDirection, HeightRule, VerticalAlign, PageBreak, TableLayoutType,
  TabStopType, ImageRun,
} = D;

const FONT = 'Times New Roman';
const mm = (v) => Math.round(v * 56.7);
const C = AlignmentType.CENTER;
const L = AlignmentType.LEFT;
const R = AlignmentType.RIGHT;
const J = AlignmentType.JUSTIFIED;
const NONE = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
const NOB = { top: NONE, bottom: NONE, left: NONE, right: NONE };
const LINE = { style: BorderStyle.SINGLE, size: 6, color: '000000' };
const ALLB = { top: LINE, bottom: LINE, left: LINE, right: LINE };
const LSP = 300; // межстрочный интервал текста (1,25)
const IND = mm(12.5);

// текст: строка или массив из строк и {t, b, i}
function runs(x, o = {}) {
  const arr = Array.isArray(x) ? x : [x];
  return arr.map((s) => {
    if (s instanceof TextRun) return s;
    const seg = typeof s === 'string' ? { t: s } : s;
    return new TextRun({ text: seg.t, font: FONT, size: o.size || 24, bold: seg.b ?? o.bold, italics: seg.i ?? o.italic });
  });
}
function p(x, o = {}) {
  return new Paragraph({
    children: runs(x, o),
    alignment: o.align || L,
    indent: o.indent,
    keepNext: o.keepNext,
    keepLines: o.keepLines,
    spacing: { before: o.before || 0, after: o.after || 0, line: o.line || 240 },
  });
}

// ---------- поле для подшивки + рамка листа ----------
function pageFrame(content) {
  const cols = [mm(5), mm(7), mm(13), mm(165)];
  const field = [['Подпись и дата', 35], ['Инв. № дубл.', 25], ['Взам. инв. №', 25], ['Подпись и дата', 35], ['Инв. № подл.', 25]];
  const H = 250;
  const fh = field.reduce((s, r) => s + r[1], 0);
  const c = (i, children, o = {}) => new TableCell({
    width: { size: cols[i], type: WidthType.DXA }, borders: o.b || NOB, rowSpan: o.rowSpan,
    textDirection: o.rot ? TextDirection.BOTTOM_TO_TOP_LEFT_TO_RIGHT : undefined, verticalAlign: o.v,
    margins: { top: 0, bottom: 0, left: o.m ?? 0, right: o.m ?? 0 }, children,
  });
  const rows = [new TableRow({ height: { value: mm(H - fh), rule: HeightRule.EXACT }, children: [
    c(0, [p('')]), c(1, [p('')]), c(2, [p('')], { rowSpan: 6 }), c(3, content, { rowSpan: 6 }),
  ] })];
  field.forEach(([label, h]) => rows.push(new TableRow({ height: { value: mm(h), rule: HeightRule.EXACT }, children: [
    c(0, [p(label, { size: 16, align: C })], { b: ALLB, rot: true, v: VerticalAlign.CENTER, m: 10 }),
    c(1, [p('', { size: 16 })], { b: ALLB }),
  ] })));
  return new Table({
    width: { size: mm(190), type: WidthType.DXA }, columnWidths: cols, layout: TableLayoutType.FIXED,
    borders: { ...NOB, insideHorizontal: NONE, insideVertical: NONE }, rows,
  });
}
function layoutTable(cols, cells) {
  return new Table({
    width: { size: cols.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: cols, layout: TableLayoutType.FIXED,
    borders: { ...NOB, insideHorizontal: NONE, insideVertical: NONE },
    rows: [new TableRow({ children: cells.map((ch, i) => new TableCell({ width: { size: cols[i], type: WidthType.DXA }, borders: NOB, children: ch })) })],
  });
}
function signer(lines, fio, year, before = 0) {
  return [
    ...lines.map((l, i) => p(l, { align: C, before: i === 0 ? before : 0 })),
    p(`____________${fio}`, { align: C, before: 60 }),
    p(`“_____”____________${year}`, { align: C, before: 60 }),
  ];
}

// ---------- лист утверждения (ГОСТ 19.104-78) ----------
function luPage({ nameLines, docName, code, year, approver, signers }) {
  const top = layoutTable([mm(75), mm(90)], [[p('')], signer(['УТВЕРЖДАЮ', ...approver.lines], approver.fio, year, mm(5))]);
  return pageFrame([
    top,
    ...nameLines.map((l, i) => p(l, { bold: true, size: 26, align: C, before: i === 0 ? mm(45) : mm(1) })),
    p(docName, { bold: true, size: 26, align: C, before: mm(5) }),
    p('Лист утверждения', { bold: true, size: 26, align: C, before: mm(5) }),
    p(`${code}-ЛУ`, { bold: true, size: 26, align: C, before: mm(8) }),
    layoutTable([mm(75), mm(90)], [[p('')], signers.flatMap((s, i) => signer(s.lines, s.fio, year, i === 0 ? mm(12) : mm(4)))]),
    p('Нормоконтролёр: ______________', { align: C, before: mm(1) }),
    p(year, { bold: true, align: C, before: mm(12) }),
  ]);
}

// ---------- титульный лист ----------
function tlPage({ nameLines, docName, code, year, sheets }) {
  return pageFrame([
    p('УТВЕРЖДЕН', { bold: true, before: mm(8) }),
    p(`${code}-ЛУ`, { before: mm(4) }),
    p('Литера ______', { before: mm(2) }),
    ...nameLines.map((l, i) => p(l, { bold: true, size: 28, align: C, before: i === 0 ? mm(72) : mm(1) })),
    p(docName, { bold: true, size: 26, align: C, before: mm(10) }),
    p(code, { bold: true, size: 26, align: C, before: mm(8) }),
    p(`Листов ${sheets}`, { align: C, before: mm(10) }),
    p(year, { bold: true, align: C, before: mm(84) }),
  ]);
}

// ---------- элементы текста ----------
const H1 = (t, o = {}) => new Paragraph({
  children: runs(t, { bold: true }), alignment: C, keepNext: true, keepLines: true,
  pageBreakBefore: o.newPage, spacing: { before: o.newPage ? 0 : 560, after: 480, line: LSP },
});
const H2 = (t) => new Paragraph({
  children: runs(t, { bold: true }), alignment: J, keepNext: true, keepLines: true,
  indent: { firstLine: IND }, spacing: { before: 480, after: 360, line: LSP },
});
const H3 = (t) => new Paragraph({
  children: runs(t, { bold: true, italic: false }), alignment: J, keepNext: true, keepLines: true,
  indent: { firstLine: IND }, spacing: { before: 60, after: 0, line: LSP },
});
const P = (t, o = {}) => new Paragraph({ children: runs(t), alignment: J, indent: { firstLine: IND }, keepNext: o.keepNext, spacing: { line: LSP, after: o.after ?? 80 } });
const NL = (n, t) => P([`${n}) `, ...(Array.isArray(t) ? t : [t])]);
const LI = (t) => new Paragraph({ children: runs(['– ', ...(Array.isArray(t) ? t : [t])]), alignment: J, indent: { firstLine: IND }, spacing: { line: LSP } });

function figure(file, widthMm, caption) {
  const buf = fs.readFileSync(file);
  // размер PNG
  const w = buf.readUInt32BE(16); const h = buf.readUInt32BE(20);
  const wpx = Math.round(widthMm / 25.4 * 96); const hpx = Math.round(wpx * h / w);
  return [
    new Paragraph({ alignment: C, keepNext: true, spacing: { before: 60, after: 60 },
      children: [new ImageRun({ type: 'png', data: buf, transformation: { width: wpx, height: hpx } })] }),
    ...(caption ? [p(caption, { align: C, after: 120, line: LSP })] : []),
  ];
}

// простая таблица с рамкой
function grid(widthsMm, header, rows, o = {}) {
  const W = widthsMm.map(mm);
  const fs_ = o.size || 20;
  const cell = (t, i, bold, keep) => new TableCell({
    width: { size: W[i], type: WidthType.DXA }, borders: ALLB, verticalAlign: VerticalAlign.CENTER,
    margins: { top: 30, bottom: 30, left: 60, right: 60 },
    children: String(t).split('\n').map((line) => p(line, { size: fs_, bold, keepNext: keep, keepLines: true, align: bold || (o.center || []).includes(i) ? C : L })),
  });
  return new Table({
    width: { size: W.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: W, layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true, children: header.map((t, i) => cell(t, i, true, true)) }),
      ...rows.map((r, k) => new TableRow({ cantSplit: true, children: r.map((t, i) => cell(t, i, false, k < rows.length - 1)) })),
    ],
  });
}

// ---------- содержание ----------
function toc(items, pages) {
  return [
    new Paragraph({ children: runs('СОДЕРЖАНИЕ', { bold: true }), alignment: C, spacing: { after: 200, line: LSP } }),
    ...items.map(([t, lvl]) => new Paragraph({
      children: [...runs(t), new TextRun({ text: `\t${pages[t] || ''}`, font: FONT, size: 24 })],
      tabStops: [{ type: TabStopType.RIGHT, position: mm(175) - 20, leader: 'dot' }],
      indent: { left: mm(lvl * 5) }, spacing: { line: LSP },
    })),
  ];
}

// ---------- лист регистрации изменений ----------
function lriTable() {
  const RW = [mm(11), mm(17), mm(17), mm(17), mm(17), mm(20), mm(20), mm(22), mm(12), mm(12)];
  const rc = (t, i, o = {}) => new TableCell({
    width: { size: o.w || RW[i], type: WidthType.DXA }, borders: ALLB,
    columnSpan: o.span, rowSpan: o.rowSpan, verticalAlign: VerticalAlign.CENTER,
    margins: { top: 20, bottom: 20, left: 30, right: 30 },
    children: [p(t, { size: 18, align: C })],
  });
  const rows = [
    new TableRow({ tableHeader: true, children: [
      rc('Изм.', 0, { rowSpan: 2 }),
      rc('Номера листов (страниц)', 1, { span: 4, w: RW[1] * 4 }),
      rc('Всего листов (страниц) в докум.', 5, { rowSpan: 2 }),
      rc('№ документа', 6, { rowSpan: 2 }),
      rc('Входящий № сопроводи-тельного документа и дата', 7, { rowSpan: 2 }),
      rc('Подп.', 8, { rowSpan: 2 }),
      rc('Дата', 9, { rowSpan: 2 }),
    ] }),
    new TableRow({ tableHeader: true, children: [rc('изменен-ных', 1), rc('заменен-ных', 2), rc('новых', 3), rc('аннулиро-ванных', 4)] }),
  ];
  for (let i = 0; i < 27; i++) rows.push(new TableRow({ height: { value: mm(8), rule: HeightRule.EXACT }, children: RW.map((w, j) => rc('', j)) }));
  return [
    new Paragraph({ children: [new PageBreak()] }),
    p('Лист регистрации изменений', { bold: true, align: C, after: 200, size: 26 }),
    new Table({ width: { size: RW.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: RW, layout: TableLayoutType.FIXED, rows }),
  ];
}

// ---------- сборка документа ----------
// Альбомный фрагмент тела документа: landscape([...абзацы]) внутри body
const landscape = (children) => ({ __landscape: children });

function build({ lu, tl, body, code, out, headBold }) {
  const frameProps = (start) => ({ page: { size: { width: mm(210), height: mm(297) }, margin: { top: mm(20), bottom: mm(15), left: mm(8), right: mm(12), header: mm(10), footer: mm(8) }, pageNumbers: start ? { start } : undefined } });
  const empty = new Header({ children: [p('')] });
  const head = new Header({ children: [
    new Paragraph({ alignment: C, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 24, bold: !!headBold })] }),
    p(code, { align: C, bold: !!headBold }),
  ] });
  const margin = { top: mm(25), bottom: mm(15), left: mm(25), right: mm(10), header: mm(8), footer: mm(5) };
  const portrait = (start) => ({ page: { size: { width: mm(210), height: mm(297) }, margin, pageNumbers: start ? { start } : undefined } });
  const land = { page: { size: { width: mm(210), height: mm(297), orientation: D.PageOrientation.LANDSCAPE }, margin } };
  // разбиваем тело на разделы: книжные и альбомные
  const chunks = [{ land: false, children: [] }];
  for (const el of body) {
    if (el && el.__landscape) {
      chunks.push({ land: true, children: el.__landscape });
      chunks.push({ land: false, children: [] });
    } else chunks[chunks.length - 1].children.push(el);
  }
  chunks[chunks.length - 1].children.push(...lriTable());
  const bodySections = chunks.filter((c) => c.children.length).map((c, i) => ({
    properties: c.land ? land : portrait(i === 0 ? 2 : undefined),
    headers: { default: head },
    children: c.children,
  }));
  const doc = new D.Document({
    styles: { default: { document: { run: { font: FONT, size: 24 } } } },
    sections: [
      { properties: frameProps(), headers: { default: empty }, children: [luPage(lu), p('', { size: 2 })] },
      { properties: frameProps(1), headers: { default: empty }, children: [tlPage(tl), p('', { size: 2 })] },
      ...bodySections,
    ],
  });
  return D.Packer.toBuffer(doc).then((b) => fs.writeFileSync(out, b));
}

module.exports = { landscape, mm, p, runs, H1, H2, H3, P, NL, LI, figure, grid, toc, build, C, L, R, J, LSP, IND };
