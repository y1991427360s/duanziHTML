"use strict";

const BUILTIN_PROJECT = {
  projectName: "示例二次接线项目",
  terminalBlocks: [
    { name: "ZD", terminals: Array.from({ length: 14 }, (_, i) => ({ number: String(i + 1) })) },
    { name: "11D", terminals: Array.from({ length: 8 }, (_, i) => ({ number: String(i + 1) })) }
  ],
  connections: [
    ["ZD","1","+KM1","公用测控及时钟同步系统柜","直流馈线柜","ZL-01","2×4"],
    ["ZD","8","-KM1","公用测控及时钟同步系统柜","直流馈线柜","ZL-01","2×4"],
    ["ZD","5","+KM2","公用测控及时钟同步系统柜","直流馈线柜","ZL-02","2×4"],
    ["ZD","12","-KM2","公用测控及时钟同步系统柜","直流馈线柜","ZL-02","2×4"],
    ["ZD","2","B+","公用测控及时钟同步系统柜","远动通信柜","DS-01","通讯线"],
    ["ZD","3","B-","公用测控及时钟同步系统柜","远动通信柜","DS-01","通讯线"],
    ["ZD","4","TX+","公用测控及时钟同步系统柜","调度数据网柜","DS-02","屏蔽双绞线"],
    ["ZD","6","TX-","公用测控及时钟同步系统柜","调度数据网柜","DS-02","屏蔽双绞线"],
    ["ZD","7","A","公用测控及时钟同步系统柜","故障录波柜","DS-03","4×1.5"],
    ["ZD","10","B","公用测控及时钟同步系统柜","故障录波柜","DS-03","4×1.5"],
    ["ZD","9","COM","公用测控及时钟同步系统柜","电能质量柜","DS-04","2×2.5"],
    ["ZD","14","SIG","公用测控及时钟同步系统柜","电能质量柜","DS-04","2×2.5"],
    ["11D","1","101","线路保护柜","断路器机构箱","KZ-01","4×2.5"],
    ["11D","6","102","线路保护柜","断路器机构箱","KZ-01","4×2.5"]
  ].map(([terminalBlock, terminal, principle, fromCabinet, toCabinet, cableNumber, cableSpec]) =>
    ({ terminalBlock, terminal, principle, fromCabinet, toCabinet, cableNumber, cableSpec })),
  settings: { direction: "DOWN", firstDistance: 10, distanceStep: 5, textHeight: 3 }
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const clone = (value) => JSON.parse(JSON.stringify(value));
const naturalCompare = (a, b) => String(a).localeCompare(String(b), "zh-CN", { numeric: true, sensitivity: "base" });
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" })[char]);
const safeFileName = (value) => String(value || "端子排项目").replace(/[\\/:*?"<>|]/g, "_");
const blockContainsConnection = (block, connection) => Boolean(block && block.name === connection.terminalBlock && block.terminals.some((terminal) => terminal.number === connection.terminal));
const connectionBelongsToBlocks = (connection, blocks) => blocks.some((block) => blockContainsConnection(block, connection));

// 1 个 CAD 单位对应 6 个 SVG 单位；导出时按 1 单位 = 1mm 折算图幅。
const UNIT_SCALE = 6;
// 电缆标签字号、标签底色高度和层间距下限统一在这里计算，避免几何与电缆分析两处公式不一致。
const layerMetrics = (settings) => {
  const labelFontSize = Math.round(8 + settings.textHeight * 1.8);
  return {
    labelFontSize,
    labelHeight: labelFontSize + 8,
    layerStep: Math.max(settings.distanceStep * UNIT_SCALE, labelFontSize + 12)
  };
};

const DataManager = {
  normalize(raw) {
    if (!raw || typeof raw !== "object") throw new Error("JSON 根节点必须是对象");
    const terminalBlocks = Array.isArray(raw.terminalBlocks) ? raw.terminalBlocks.map((block, index) => ({
      name: String(block?.name ?? `端子排${index + 1}`).trim() || `端子排${index + 1}`,
      layoutGroup: String(block?.layoutGroup ?? "").trim(),
      terminals: Array.isArray(block?.terminals) ? block.terminals.map((terminal) => ({ number: String(terminal?.number ?? "").trim() })) : []
    })) : [];
    const connections = Array.isArray(raw.connections) ? raw.connections.map((connection) => ({
      terminalBlock: String(connection?.terminalBlock ?? "").trim(),
      terminal: String(connection?.terminal ?? "").trim(),
      principle: String(connection?.principle ?? "").trim(),
      fromCabinet: String(connection?.fromCabinet ?? "").trim(),
      toCabinet: String(connection?.toCabinet ?? "").trim(),
      cableNumber: String(connection?.cableNumber ?? "").trim(),
      cableSpec: String(connection?.cableSpec ?? "").trim()
    })) : [];
    return {
      projectName: String(raw.projectName ?? "未命名项目").trim() || "未命名项目",
      terminalBlocks,
      connections,
      settings: {
        direction: raw.settings?.direction === "UP" ? "UP" : "DOWN",
        firstDistance: this.numberInRange(raw.settings?.firstDistance, 10, 5, 30),
        distanceStep: this.numberInRange(raw.settings?.distanceStep, 5, 2, 15),
        textHeight: this.numberInRange(raw.settings?.textHeight, 3, 2, 6)
      }
    };
  },
  numberInRange(value, fallback, min, max) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
  },
  download(content, filename, type) {
    const blob = new Blob([content], { type });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }
};

const ValidationManager = {
  validate(project) {
    const issues = [];
    const terminalsByBlockName = new Map();
    project.terminalBlocks.forEach((block) => {
      if (!terminalsByBlockName.has(block.name)) terminalsByBlockName.set(block.name, new Set());
      const knownNumbers = terminalsByBlockName.get(block.name);
      const numbers = new Set();
      block.terminals.forEach((terminal) => {
        if (!terminal.number) issues.push({ type: "error", block: block.name, text: `${block.name} 存在空端子号` });
        else if (numbers.has(terminal.number)) issues.push({ type: "error", block: block.name, text: `${block.name}-${terminal.number} 端子号重复` });
        else if (knownNumbers.has(terminal.number)) issues.push({ type: "error", block: block.name, text: `${block.name}-${terminal.number} 在不同分块中重复` });
        numbers.add(terminal.number);
        knownNumbers.add(terminal.number);
      });
    });
    const pointCounts = new Map();
    const cables = new Map();
    project.connections.forEach((connection, index) => {
      const block = project.terminalBlocks.find((item) => blockContainsConnection(item, connection));
      const prefix = connection.terminalBlock || "未指定端子排";
      if (!project.terminalBlocks.some((item) => item.name === connection.terminalBlock)) issues.push({ type: "error", index, block: connection.terminalBlock, text: `${prefix}：端子排不存在` });
      else if (!block) issues.push({ type: "error", index, block: connection.terminalBlock, text: `${prefix}-${connection.terminal || "空"}：端子不存在` });
      if (!connection.cableNumber) issues.push({ type: "error", index, block: connection.terminalBlock, text: `${prefix}-${connection.terminal || "空"}：缺少电缆号` });
      else {
        const cable = cables.get(connection.cableNumber) || { block: connection.terminalBlock, spec: false, destination: false };
        cable.spec = cable.spec || Boolean(connection.cableSpec);
        cable.destination = cable.destination || Boolean(connection.toCabinet);
        cables.set(connection.cableNumber, cable);
      }
      const key = `${connection.terminalBlock}\u0000${connection.terminal}`;
      pointCounts.set(key, (pointCounts.get(key) || 0) + 1);
    });
    pointCounts.forEach((count, key) => {
      if (count > 1) {
        const [block, terminal] = key.split("\u0000");
        issues.push({ type: "warning", block, text: `${block}-${terminal} 存在多个接线关系` });
      }
    });
    cables.forEach((cable, number) => {
      if (!cable.destination) issues.push({ type: "warning", block: cable.block, text: `${number} 缺少去向` });
      if (!cable.spec) issues.push({ type: "warning", block: cable.block, text: `${number} 缺少规格，请补填后再出图` });
    });
    return issues;
  },
  isConnectionValid(project, connection) {
    return project.terminalBlocks.some((block) => blockContainsConnection(block, connection));
  },
  isConnectionDrawable(project, connection) {
    return Boolean(connection.cableNumber && this.isConnectionValid(project, connection));
  }
};

const CableAnalyzer = {
  build(project, blocks, geometry) {
    const connections = project.connections.filter((connection) => connectionBelongsToBlocks(connection, blocks) && ValidationManager.isConnectionDrawable(project, connection));
    const grouped = new Map();
    connections.forEach((connection) => {
      if (!grouped.has(connection.cableNumber)) grouped.set(connection.cableNumber, []);
      grouped.get(connection.cableNumber).push(connection);
    });
    const orderedGroups = [...grouped.entries()].map(([number, points]) => {
      const leftmostPoint = points.reduce((leftmost, point) => {
        const position = geometry.terminalPositions.get(`${point.terminalBlock}\u0000${point.terminal}`);
        if (!position) return leftmost;
        return !leftmost || position.globalIndex < leftmost.position.globalIndex ? { connection: point, position } : leftmost;
      }, null);
      return { number, points, leftmostPoint, leftmostTerminalIndex: leftmostPoint?.position.globalIndex ?? Number.MAX_SAFE_INTEGER };
    }).sort((a, b) => a.leftmostTerminalIndex - b.leftmostTerminalIndex || naturalCompare(a.number, b.number));
    return orderedGroups.map(({ number, points, leftmostPoint, leftmostTerminalIndex }, index) => {
      const laneOffset = project.settings.firstDistance * geometry.unitScale + index * geometry.layerStep;
      const laneY = geometry.direction === "DOWN" ? geometry.pinY + laneOffset : geometry.pinY - laneOffset;
      const routedPoints = points.map((point) => ({
        connection: point,
        x: geometry.terminalPositions.get(`${point.terminalBlock}\u0000${point.terminal}`).centerX
      })).sort((a, b) => a.x - b.x);
      return {
        number, index, laneY, points: routedPoints, leftmostTerminalIndex,
        leftmostReference: leftmostPoint ? `${leftmostPoint.connection.terminalBlock}-${leftmostPoint.connection.terminal}` : "—",
        spec: points.find((point) => point.cableSpec)?.cableSpec || "未填写",
        destination: points.find((point) => point.toCabinet)?.toCabinet || "未填写",
        origin: points.find((point) => point.fromCabinet)?.fromCabinet || "未填写"
      };
    });
  },
  summarize(cables) {
    return { cableCount: cables.length, connectionCount: cables.reduce((sum, cable) => sum + cable.points.length, 0) };
  }
};

const TerminalRenderer = {
  createGeometry(project, blocks) {
    const unitScale = UNIT_SCALE;
    const terminalWidth = 5 * unitScale;
    const pitch = terminalWidth;
    const blockNameWidth = 10 * unitScale;
    const terminalZoneHeight = 10 * unitScale;
    const numberBandHeight = 5 * unitScale;
    const terminalHeight = terminalZoneHeight * 2 + numberBandHeight;
    const terminalTextSize = project.settings.textHeight * unitScale;
    const startX = 72;
    const blockConnections = project.connections.filter((connection) => connectionBelongsToBlocks(connection, blocks));
    const cableCount = new Set(blockConnections.filter((connection) => connection.cableNumber).map((connection) => connection.cableNumber)).size;
    const { labelFontSize, labelHeight, layerStep } = layerMetrics(project.settings);
    const maxOffset = project.settings.firstDistance * unitScale + Math.max(0, cableCount - 1) * layerStep;
    const direction = project.settings.direction;
    const terminalY = direction === "DOWN" ? 88 : maxOffset + 110;
    const terminalBottom = terminalY + terminalHeight;
    const numberBandY = terminalY + terminalZoneHeight;
    const numberCenterY = numberBandY + numberBandHeight / 2;
    const principleCenterY = direction === "DOWN"
      ? numberBandY + numberBandHeight + terminalZoneHeight / 2
      : terminalY + terminalZoneHeight / 2;
    const pinY = direction === "DOWN" ? terminalBottom : terminalY;
    const terminalPositions = new Map();
    const blockLayouts = [];
    let cursorX = startX;
    let globalIndex = 0;
    blocks.forEach((block) => {
      const blockStartX = cursorX;
      const terminalStartX = blockStartX + blockNameWidth;
      block.terminals.forEach((terminal, terminalIndex) => {
        const x = terminalStartX + terminalIndex * pitch;
        terminalPositions.set(`${block.name}\u0000${terminal.number}`, { x, centerX: x + terminalWidth / 2, globalIndex, blockName: block.name, terminal: terminal.number });
        globalIndex++;
      });
      const width = blockNameWidth + Math.max(1, block.terminals.length) * terminalWidth;
      blockLayouts.push({ block, startX: blockStartX, terminalStartX, width, endX: blockStartX + width });
      cursorX = blockStartX + width;
    });
    const terminalRight = Math.max(startX + blockNameWidth + terminalWidth, cursorX);
    const estimateWidth = (value, size = labelFontSize) => [...String(value || "")].reduce((sum, char) => sum + (/[^\x00-\xff]/.test(char) ? 1 : .64), 0) * size;
    const maxCableWidth = Math.max(0, ...blockConnections.map((connection) => estimateWidth(connection.cableNumber)));
    const maxDestinationWidth = Math.max(0, ...blockConnections.map((connection) => estimateWidth(`至 ${connection.toCabinet}`, Math.max(9, labelFontSize - 2))));
    const maxSpecWidth = Math.max(0, ...blockConnections.map((connection) => estimateWidth(connection.cableSpec, Math.max(9, labelFontSize - 2))));
    const busX = terminalRight + 110;
    const numberX = busX + 70;
    const numberColumnWidth = Math.max(160, maxCableWidth + 80);
    const chevronBaseX = numberX + numberColumnWidth + 60;
    const chevronTipX = chevronBaseX + 30;
    const destinationX = chevronTipX + 60;
    const destinationColumnWidth = Math.max(420, maxDestinationWidth + 120);
    const specColumnWidth = Math.max(200, maxSpecWidth + 100);
    const sceneWidth = Math.max(1500, destinationX + destinationColumnWidth + specColumnWidth + 100);
    const sceneHeight = direction === "DOWN"
      ? Math.max(430, pinY + maxOffset + 100)
      : Math.max(430, terminalBottom + 100);
    return {
      direction, terminalWidth, terminalHeight, terminalZoneHeight, numberBandHeight, numberBandY, numberCenterY,
      principleCenterY, terminalTextSize, blockNameWidth, pitch, startX, unitScale, pinY, terminalY, busX,
      numberX, numberColumnWidth, chevronBaseX, chevronTipX, destinationX, sceneWidth, sceneHeight,
      labelFontSize, labelHeight, layerStep, terminalPositions, blockLayouts
    };
  },
  terminalMarkup(geometry, principleByTerminal) {
    return geometry.blockLayouts.map(({ block, startX, terminalStartX, width, endX }) => {
      const nameCenterX = startX + geometry.blockNameWidth / 2;
      const nameCenterY = geometry.terminalY + geometry.terminalHeight / 2;
      const blockFrame = `<g class="terminal-block-frame">
        <rect x="${startX}" y="${geometry.terminalY}" width="${width}" height="${geometry.terminalHeight}"/>
        <line x1="${terminalStartX}" y1="${geometry.terminalY}" x2="${terminalStartX}" y2="${geometry.terminalY + geometry.terminalHeight}"/>
        <line x1="${terminalStartX}" y1="${geometry.numberBandY}" x2="${endX}" y2="${geometry.numberBandY}"/>
        <line x1="${terminalStartX}" y1="${geometry.numberBandY + geometry.numberBandHeight}" x2="${endX}" y2="${geometry.numberBandY + geometry.numberBandHeight}"/>
        <text class="terminal-block-name" x="${nameCenterX}" y="${nameCenterY}" font-size="${geometry.terminalTextSize}" transform="rotate(-90 ${nameCenterX} ${nameCenterY})">${escapeHtml(block.name)}</text>
      </g>`;
      const terminals = block.terminals.map((terminal) => {
        const position = geometry.terminalPositions.get(`${block.name}\u0000${terminal.number}`);
        const x = position.x;
        const centerX = position.centerX;
        const principle = principleByTerminal.get(`${block.name}\u0000${terminal.number}`) || "";
        return `<g class="terminal-group" data-block="${escapeHtml(block.name)}" data-terminal="${escapeHtml(terminal.number)}">
        <rect class="terminal-hit-area" x="${x}" y="${geometry.terminalY}" width="${geometry.terminalWidth}" height="${geometry.terminalHeight}"/>
        <line class="terminal-divider" x1="${x + geometry.terminalWidth}" y1="${geometry.terminalY}" x2="${x + geometry.terminalWidth}" y2="${geometry.terminalY + geometry.terminalHeight}"/>
        <text class="terminal-number" x="${centerX}" y="${geometry.numberCenterY}" font-size="${geometry.terminalTextSize}" transform="rotate(-90 ${centerX} ${geometry.numberCenterY})">${escapeHtml(terminal.number)}</text>
        ${principle ? `<text class="principle-label" x="${centerX}" y="${geometry.principleCenterY}" font-size="${geometry.terminalTextSize}" transform="rotate(-90 ${centerX} ${geometry.principleCenterY})">${escapeHtml(principle)}</text>` : ""}
      </g>`;
      }).join("");
      return blockFrame + terminals;
    }).join("");
  }
};

const CableRenderer = {
  markup(cables, geometry, selectedCable) {
    const fontSize = geometry.labelFontSize;
    return cables.map((cable) => {
      const selected = cable.number === selectedCable ? " selected" : selectedCable ? " dimmed" : "";
      const labelY = cable.laneY;
      const minX = Math.min(...cable.points.map((point) => point.x));
      const paths = cable.points.map((point) => `<path class="cable-line" d="M ${point.x} ${geometry.pinY} V ${cable.laneY}"/>`).join("");
      const trunk = `<path class="cable-line" d="M ${minX} ${cable.laneY} H ${geometry.busX}"/>`;
      return `<g class="cable-group${selected}" data-cable="${escapeHtml(cable.number)}">
        ${paths}${trunk}
        <rect class="cable-label-bg" x="${geometry.numberX - 10}" y="${(labelY - (fontSize * .75 + 3)).toFixed(1)}" width="${geometry.numberColumnWidth - 12}" height="${geometry.labelHeight}" rx="1"/>
        <text class="cable-label" x="${geometry.numberX}" y="${labelY + 4}" font-size="${fontSize}">${escapeHtml(cable.number)}</text>
        <path class="cable-chevron" d="M ${geometry.chevronBaseX} ${labelY - 9} L ${geometry.chevronTipX} ${labelY} L ${geometry.chevronBaseX} ${labelY + 9} M ${geometry.chevronTipX} ${labelY} H ${geometry.sceneWidth - 34}"/>
        <text class="cable-destination" x="${geometry.destinationX}" y="${labelY - 4}" font-size="${Math.max(9, fontSize - 2)}">至 ${escapeHtml(cable.destination)}</text>
        <text class="cable-spec" x="${geometry.sceneWidth - 42}" y="${labelY - 4}" font-size="${Math.max(9, fontSize - 2)}" text-anchor="end">${escapeHtml(cable.spec)}</text>
      </g>`;
    }).join("");
  }
};

// 把当前视图打包成「参数区」，塞进固定的 Python 模板，产出一键出 DXF 的脚本。
const PythonExporter = {
  buildParams(project, blocks, viewName) {
    const names = new Set(blocks.map((block) => block.name));
    return {
      projectName: project.projectName,
      viewName,
      direction: project.settings.direction,
      firstDistance: project.settings.firstDistance,
      distanceStep: project.settings.distanceStep,
      textHeight: project.settings.textHeight,
      terminalBlocks: blocks.map((block) => ({ name: block.name, terminals: block.terminals.map((terminal) => terminal.number) })),
      // 端子排名称对得上就一起导出，端子号有问题的记录交给脚本报「跳过」，不在这里悄悄丢掉。
      connections: project.connections.filter((connection) => names.has(connection.terminalBlock)).map((connection) => ({
        terminalBlock: connection.terminalBlock,
        terminal: connection.terminal,
        principle: connection.principle,
        fromCabinet: connection.fromCabinet,
        toCabinet: connection.toCabinet,
        cableNumber: connection.cableNumber,
        cableSpec: connection.cableSpec
      }))
    };
  },
  build(project, blocks, viewName) {
    if (!window.PYTHON_DXF_TEMPLATE) throw new Error("缺少 python-template.js");
    const params = JSON.stringify(this.buildParams(project, blocks, viewName), null, 2);
    return window.PYTHON_DXF_TEMPLATE.replace("__PARAMS__", () => params);
  }
};

const ProjectManager = {
  project: DataManager.normalize(clone(BUILTIN_PROJECT)),
  activeBlockIndex: 0,
  selectedCable: null,
  sourceName: "内置示例",
  get activeBlock() { return this.project.terminalBlocks[this.activeBlockIndex] || null; },
  get activeBlocks() {
    const active = this.activeBlock;
    if (!active) return [];
    if (!active.layoutGroup) return [active];
    return this.project.terminalBlocks.filter((block) => block.layoutGroup === active.layoutGroup);
  },
  get activeViewName() {
    const active = this.activeBlock;
    return active?.layoutGroup || active?.name || "";
  },
  setProject(project, sourceName) {
    this.project = DataManager.normalize(project);
    this.activeBlockIndex = 0;
    this.selectedCable = null;
    this.sourceName = sourceName;
  },
  markChanged() { this.sourceName = "未保存更改"; }
};

const WorkflowManager = {
  step: 1,
  maxStep: 1,
  pendingProject: null,
  parsedConnections: [],
  parsedCables: [],
  importMode: "replace",
  draftKey: "terminal-planner-workflow-draft-v3",
  subtitles: {
    1: "直接粘贴厂家端子排清单",
    2: "核对端子排名称和端子顺序",
    3: "批量导入接线资料",
    4: "检查结果并进入接线预览"
  },
  init() {
    this.bindEvents();
    this.restoreDraft();
  },
  bindEvents() {
    $("#workflowBtn").addEventListener("click", () => this.open());
    $("#workflowCloseBtn").addEventListener("click", () => this.close());
    $("#workflowOverlay").addEventListener("click", (event) => { if (event.target.id === "workflowOverlay") this.close(); });
    $("#parseTerminalSequenceBtn").addEventListener("click", () => this.parseTerminalSequence());
    $("#useCurrentTemplateBtn").addEventListener("click", () => this.useCurrentTemplate());
    $("#confirmTemplateBtn").addEventListener("click", () => this.confirmTemplate());
    $("#importTemplateOnlyBtn").addEventListener("click", () => this.importTemplateOnly());
    $("#parseConnectionsBtn").addEventListener("click", () => this.parseConnectionText());
    $("#replaceConnectionsMode").addEventListener("click", () => this.setImportMode("replace"));
    $("#appendConnectionsMode").addEventListener("click", () => this.setImportMode("append"));
    $("#applyConnectionsBtn").addEventListener("click", () => this.applyConnections());
    $("#workflowExportPyBtn").addEventListener("click", () => { UIManager.exportPython(); });
    $("#finishWorkflowBtn").addEventListener("click", () => this.finish());
    $$('[data-workflow-back]').forEach((button) => button.addEventListener("click", () => this.goToStep(Number(button.dataset.workflowBack))));
    $$('[data-workflow-nav]').forEach((button) => button.addEventListener("click", () => {
      const target = Number(button.dataset.workflowNav);
      if (target <= this.maxStep) this.goToStep(target);
    }));
    ["terminalSequenceInput", "workflowConnectionInput", "workflowFromCabinet", "workflowCablePrefix"].forEach((id) => $("#" + id).addEventListener("input", () => this.persistDraft()));
    window.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("#workflowOverlay").hidden) this.close(); });
  },
  open() {
    $("#workflowOverlay").hidden = false;
    document.body.style.overflow = "hidden";
    this.goToStep(this.step);
  },
  close() {
    $("#workflowOverlay").hidden = true;
    document.body.style.overflow = "";
    this.persistDraft();
  },
  finish() {
    this.close();
    UIManager.switchTab("connections");
    SvgViewport.fit();
    UIManager.toast("工作流已完成，接线预览已生成");
  },
  goToStep(step) {
    this.step = Math.min(4, Math.max(1, step));
    this.maxStep = Math.max(this.maxStep, this.step);
    $$(".workflow-panel").forEach((panel) => panel.classList.toggle("active", Number(panel.dataset.workflowPanel) === this.step));
    $$(".workflow-step").forEach((button) => {
      const number = Number(button.dataset.workflowNav);
      button.classList.toggle("active", number === this.step);
      button.classList.toggle("completed", number < this.step);
    });
    $("#workflowSubtitle").textContent = this.subtitles[this.step];
    this.persistDraft();
  },
  tokenizeTerminalSequence(text) {
    return String(text || "")
      .split(/[\t,，、]+/)
      .map((token) => token.trim().replace(/[。.!！]+$/g, ""))
      .filter(Boolean);
  },
  parseTerminalSequence() {
    const resultBox = $("#templateParseResult");
    try {
      const source = String($("#terminalSequenceInput").value || "");
      const segments = source.split(/\r?\n\s*\r?\n+/).map((segment) => segment.trim()).filter(Boolean);
      if (!segments.length) throw new Error("请先粘贴端子排名称和端子号");
      const terminalBlocks = [];
      segments.forEach((segment, segmentIndex) => {
        const units = segment.split(/[;；\r\n]+/).map((unit) => unit.trim()).filter(Boolean);
        const groupBlocks = [];
        units.forEach((unit) => {
          const [name, ...numbers] = this.tokenizeTerminalSequence(unit);
          if (!name) throw new Error(`第 ${segmentIndex + 1} 组里有一块端子排没有名称`);
          if (!numbers.length) throw new Error(`端子排“${name}”后面没有端子号`);
          const block = { name, layoutGroup: "", terminals: numbers.map((number) => ({ number })) };
          groupBlocks.push(block);
          terminalBlocks.push(block);
        });
        if (groupBlocks.length > 1) groupBlocks.forEach((block) => { block.layoutGroup = `组合端子排-${segmentIndex + 1}`; });
      });
      if (!terminalBlocks.length) throw new Error("没有解析到任何端子排");
      this.pendingProject = DataManager.normalize({
        projectName: ProjectManager.project.projectName || "手动端子排模板",
        terminalBlocks,
        connections: [],
        settings: ProjectManager.project.settings
      });
      const terminalCount = this.pendingProject.terminalBlocks.reduce((sum, block) => sum + block.terminals.length, 0);
      resultBox.className = "workflow-inline-result success";
      resultBox.textContent = `解析成功：${this.pendingProject.terminalBlocks.length} 块端子排，${segments.length} 个物理组合，${terminalCount} 个端子`;
      this.renderTemplateReview();
      this.goToStep(2);
    } catch (error) {
      resultBox.className = "workflow-inline-result error";
      resultBox.textContent = `解析失败：${error.message}`;
    }
  },
  useCurrentTemplate() {
    if (!ProjectManager.project.terminalBlocks.length) return UIManager.toast("当前项目没有可使用的端子模板");
    this.pendingProject = DataManager.normalize({ ...clone(ProjectManager.project), connections: [] });
    this.renderTemplateReview();
    this.goToStep(2);
  },
  renderTemplateReview() {
    const project = this.pendingProject;
    if (!project) return;
    $("#templateReview").innerHTML = project.terminalBlocks.map((block) => `<div class="template-review-row"><strong>${escapeHtml(block.name)}</strong><span>${block.terminals.length} 个端子${block.layoutGroup ? " · 连续组合" : " · 独立"}</span><div class="template-terminal-sequence" title="${escapeHtml(block.terminals.map((terminal) => terminal.number).join("、"))}">${escapeHtml(block.terminals.map((terminal) => terminal.number).join(" · "))}</div></div>`).join("");
    const issues = ValidationManager.validate(project);
    const suspicious = [];
    project.terminalBlocks.forEach((block) => {
      if (/待确认/.test(block.name) || block.terminals.some((terminal) => /待确认/.test(terminal.number))) suspicious.push(`${block.name} 含有待确认内容`);
      const looksLikeBlockName = block.terminals.filter((terminal) => /[A-Za-z]D$/i.test(terminal.number)).map((terminal) => terminal.number);
      if (looksLikeBlockName.length) suspicious.push(`${block.name} 里的端子号 ${looksLikeBlockName.join("、")} 看起来像端子排名称，确认是不是漏了分号或换行`);
    });
    const allIssues = [...issues.map((issue) => issue.text), ...suspicious];
    $("#templateReviewIssues").innerHTML = allIssues.length ? allIssues.map((text) => `<div class="issue warning"><strong>请核对：</strong>${escapeHtml(text)}</div>`).join("") : `<div class="workflow-review-ok">模板结构正常，可以继续导入接线资料。</div>`;
  },
  confirmTemplate() {
    if (!this.pendingProject) return;
    ProjectManager.setProject(clone(this.pendingProject), "工作流空模板");
    UIManager.renderAll(false);
    this.goToStep(3);
  },
  importTemplateOnly() {
    if (!this.pendingProject) return;
    ProjectManager.setProject(clone(this.pendingProject), "工作流端子排模板");
    UIManager.renderAll(false);
    this.close();
    UIManager.toast(`已导入 ${this.pendingProject.terminalBlocks.length} 个端子排，接线可稍后导入`);
  },
  setImportMode(mode) {
    this.importMode = mode;
    $("#replaceConnectionsMode").classList.toggle("active", mode === "replace");
    $("#appendConnectionsMode").classList.toggle("active", mode === "append");
    this.persistDraft();
  },
  splitConnectionRecords(text) {
    return String(text || "").split(/[;；\r\n]+/).map((record) => record.trim()).filter(Boolean);
  },
  splitRecordFields(record) {
    const fields = String(record).split(/[\t,，、]/).map((field) => field.trim());
    while (fields.length && !fields[fields.length - 1]) fields.pop();
    return fields;
  },
  resolveTerminalReference(reference) {
    const normalized = String(reference || "").trim();
    if (!normalized) return { error: "缺少端子号" };
    const names = [...new Set(ProjectManager.project.terminalBlocks.map((block) => block.name))].sort((a, b) => b.length - a.length);
    const candidates = names.filter((name) => normalized.toUpperCase().startsWith(name.toUpperCase()));
    if (!candidates.length) return { error: `无法匹配端子排：${normalized}` };
    let lastError = "";
    for (const name of candidates) {
      const wanted = normalized.slice(name.length).replace(/^[-_\s]+/, "");
      if (!wanted) { lastError = `${normalized} 缺少端子号`; continue; }
      let matched = null;
      ProjectManager.project.terminalBlocks.forEach((block) => {
        if (matched || block.name !== name) return;
        matched = block.terminals.find((terminal) => terminal.number.toUpperCase() === wanted.toUpperCase()) || null;
      });
      if (matched) return { block: name, terminal: matched.number };
      lastError = `${name}-${wanted} 端子不存在`;
    }
    return { error: lastError || `无法匹配端子排：${normalized}` };
  },
  nextCableNumber(prefix, used) {
    let sequence = 1;
    let number = `${prefix}-${String(sequence).padStart(2, "0")}`;
    while (used.has(number)) number = `${prefix}-${String(++sequence).padStart(2, "0")}`;
    used.add(number);
    return number;
  },
  parseConnectionText() {
    const records = this.splitConnectionRecords($("#workflowConnectionInput").value);
    const fromCabinet = ($("#workflowFromCabinet").value || "").trim();
    const prefix = ($("#workflowCablePrefix").value || "").trim() || "WL";
    const globalIssues = [];
    if (!records.length) {
      this.parsedConnections = [];
      this.parsedCables = [];
      const summary = $("#connectionPreviewSummary");
      summary.className = "connection-preview-summary";
      summary.textContent = "尚未导入接线资料。可以先完成端子排导入，接线稍后再补充。";
      $("#connectionPreviewBody").innerHTML = `<tr><td colspan="6">暂无接线记录</td></tr>`;
      $("#applyConnectionsBtn").disabled = true;
      this.persistDraft();
      return;
    }
    const rows = records.map((record, index) => {
      const fields = this.splitRecordFields(record);
      const [reference = "", principle = "", toCabinet = ""] = fields;
      const errors = [];
      const warnings = [];
      if (fields.length > 3) errors.push("一条记录最多 3 项：端子号、原理号、去向柜");
      const resolved = this.resolveTerminalReference(reference);
      if (resolved.error) errors.push(resolved.error);
      if (!principle) warnings.push("原理号为空");
      return {
        sourceIndex: index + 1, terminalReference: reference, errors, warnings,
        connection: {
          terminalBlock: resolved.block || "", terminal: resolved.terminal || "",
          principle, fromCabinet, toCabinet, cableNumber: "", cableSpec: ""
        }
      };
    });
    const seen = new Map();
    rows.forEach((row) => {
      if (!row.connection.terminalBlock) return;
      const key = `${row.connection.terminalBlock}-${row.connection.terminal}`;
      if (seen.has(key)) row.warnings.push(`与第 ${seen.get(key)} 条记录接在同一个端子上`);
      else seen.set(key, row.sourceIndex);
    });
    const used = new Set(this.importMode === "append" ? ProjectManager.project.connections.map((connection) => connection.cableNumber) : []);
    const cables = [];
    let bucket = [];
    rows.forEach((row) => {
      bucket.push(row);
      if (row.connection.toCabinet) { cables.push({ rows: bucket, toCabinet: row.connection.toCabinet, closed: true }); bucket = []; }
    });
    if (bucket.length) cables.push({ rows: bucket, toCabinet: "", closed: false });
    cables.forEach((cable) => {
      cable.number = this.nextCableNumber(prefix, used);
      cable.rows.forEach((row) => {
        row.cableNumber = cable.number;
        row.connection.cableNumber = cable.number;
        row.connection.toCabinet = cable.toCabinet;
        if (!cable.closed) row.warnings.push("这一段末尾没有去向柜，暂时单独算一根电缆");
      });
    });
    this.parsedConnections = rows;
    this.parsedCables = cables;
    if (cables.some((cable) => !cable.closed)) globalIssues.push("末尾有记录没有写去向柜");
    this.renderConnectionPreview(globalIssues);
  },
  renderConnectionPreview(globalIssues = []) {
    const rows = this.parsedConnections;
    const errorCount = rows.reduce((sum, row) => sum + row.errors.length, 0);
    const warningCount = rows.reduce((sum, row) => sum + row.warnings.length, 0);
    const cableCount = (this.parsedCables || []).length;
    const summary = $("#connectionPreviewSummary");
    summary.className = `connection-preview-summary ${errorCount ? "error" : "success"}`;
    summary.textContent = errorCount
      ? `解析到 ${rows.length} 条记录，其中 ${errorCount} 处错误，请修正原始文字后重新解析。`
      : `解析成功：${rows.length} 个接线点，归为 ${cableCount} 根电缆${warningCount ? `，${warningCount} 处提醒` : ""}${globalIssues.length ? `。${globalIssues.join("；")}` : ""}`;
    $("#connectionPreviewBody").innerHTML = rows.length ? rows.map((row) => {
      const connection = row.connection;
      const state = row.errors.length ? "error" : row.warnings.length ? "warn" : "ok";
      const stateText = row.errors.length ? "错误" : row.warnings.length ? "提醒" : "正常";
      const note = [...row.errors, ...row.warnings].join("；") || "—";
      return `<tr title="${escapeHtml(note)}"><td><span class="row-status ${state}">${stateText}</span></td><td>${escapeHtml(connection.terminalBlock ? `${connection.terminalBlock}-${connection.terminal}` : row.terminalReference)}</td><td>${escapeHtml(connection.principle)}</td><td>${escapeHtml(row.cableNumber || "—")}</td><td title="${escapeHtml(connection.toCabinet)}">${escapeHtml(connection.toCabinet || "—")}</td><td>${escapeHtml(note)}</td></tr>`;
    }).join("") : `<tr><td colspan="6">没有可显示的记录</td></tr>`;
    $("#applyConnectionsBtn").disabled = Boolean(errorCount || !rows.length);
    this.persistDraft();
  },
  applyConnections() {
    const connections = this.parsedConnections.filter((row) => !row.errors.length).map((row) => row.connection);
    if (!connections.length) return;
    ProjectManager.project.connections = this.importMode === "append" ? [...ProjectManager.project.connections, ...connections] : connections;
    ProjectManager.markChanged();
    ProjectManager.activeBlockIndex = Math.max(0, ProjectManager.project.terminalBlocks.findIndex((block) => blockContainsConnection(block, connections[0])));
    ProjectManager.selectedCable = null;
    UIManager.renderAll(false);
    this.renderCompletionSummary();
    this.goToStep(4);
  },
  renderCompletionSummary() {
    const project = ProjectManager.project;
    const cableCount = new Set(project.connections.map((connection) => connection.cableNumber).filter(Boolean)).size;
    const issues = ValidationManager.validate(project);
    const values = [
      ["端子排", project.terminalBlocks.length],
      ["端子总数", project.terminalBlocks.reduce((sum, block) => sum + block.terminals.length, 0)],
      ["接线点", project.connections.length],
      ["唯一电缆", cableCount]
    ];
    $("#workflowSummaryGrid").innerHTML = values.map(([label, value]) => `<div class="workflow-summary-item"><span>${label}</span><strong>${value}</strong></div>`).join("");
    $(".workflow-next-actions span").textContent = issues.length ? `已生成预览，同时发现 ${issues.length} 个数据提示；规格未填写不影响出图，脚本会把该列写成“未填写”。` : "数据检查通过，可以直接生成出图脚本。";
  },
  persistDraft() {
    try {
      localStorage.setItem(this.draftKey, JSON.stringify({
        terminalSequenceText: $("#terminalSequenceInput")?.value || "",
        connectionText: $("#workflowConnectionInput")?.value || "",
        fromCabinet: $("#workflowFromCabinet")?.value || "",
        cablePrefix: $("#workflowCablePrefix")?.value || "",
        importMode: this.importMode
      }));
    } catch (_) { /* 本地文件模式下存储不可用时不影响主流程。 */ }
  },
  restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(this.draftKey) || "null");
      if (!draft) return;
      $("#terminalSequenceInput").value = draft.terminalSequenceText || "";
      $("#workflowConnectionInput").value = draft.connectionText || "";
      $("#workflowFromCabinet").value = draft.fromCabinet || "";
      $("#workflowCablePrefix").value = draft.cablePrefix || "";
      this.importMode = draft.importMode === "append" ? "append" : "replace";
      this.setImportMode(this.importMode);
    } catch (_) { /* 忽略损坏的草稿。 */ }
  }
};

const SvgViewport = {
  svg: null,
  scene: null,
  fitView: null,
  view: null,
  dragging: false,
  pointer: null,
  init(svg) {
    this.svg = svg;
    svg.addEventListener("wheel", (event) => this.onWheel(event), { passive: false });
    svg.addEventListener("pointerdown", (event) => this.onPointerDown(event));
    window.addEventListener("pointermove", (event) => this.onPointerMove(event));
    window.addEventListener("pointerup", () => this.onPointerUp());
    svg.addEventListener("dblclick", () => this.fit());
    new ResizeObserver(() => { if (this.scene) this.fit(); }).observe(svg);
  },
  setScene(width, height, preserve = false) {
    this.scene = { width, height };
    if (!preserve || !this.view) this.fit();
  },
  fit() {
    if (!this.scene || !this.svg.clientWidth || !this.svg.clientHeight) return;
    const padding = 22;
    const aspect = this.svg.clientWidth / this.svg.clientHeight;
    let width = this.scene.width + padding * 2;
    let height = this.scene.height + padding * 2;
    if (width / height > aspect) height = width / aspect;
    else width = height * aspect;
    this.fitView = { x: (this.scene.width - width) / 2, y: (this.scene.height - height) / 2, width, height };
    this.view = { ...this.fitView };
    this.apply();
  },
  reset100() {
    if (!this.fitView) return;
    const width = Math.min(this.fitView.width * 5, Math.max(this.fitView.width * .18, this.svg.clientWidth));
    const height = width * this.svg.clientHeight / this.svg.clientWidth;
    this.view = { x: (this.scene.width - width) / 2, y: (this.scene.height - height) / 2, width, height };
    this.apply();
  },
  zoom(factor, clientX, clientY) {
    if (!this.view) return;
    const rect = this.svg.getBoundingClientRect();
    const px = clientX == null ? .5 : (clientX - rect.left) / rect.width;
    const py = clientY == null ? .5 : (clientY - rect.top) / rect.height;
    const nextWidth = Math.min(this.fitView.width * 5, Math.max(this.fitView.width * .18, this.view.width * factor));
    const nextHeight = nextWidth * rect.height / rect.width;
    const worldX = this.view.x + px * this.view.width;
    const worldY = this.view.y + py * this.view.height;
    this.view = { x: worldX - px * nextWidth, y: worldY - py * nextHeight, width: nextWidth, height: nextHeight };
    this.apply();
  },
  onWheel(event) { event.preventDefault(); this.zoom(event.deltaY > 0 ? 1.12 : .89, event.clientX, event.clientY); },
  onPointerDown(event) {
    if (event.button !== 0 || event.target.closest(".cable-group, .terminal-group")) return;
    this.dragging = true;
    this.pointer = { x: event.clientX, y: event.clientY, view: { ...this.view } };
    $("#canvasWrap").classList.add("dragging");
    this.svg.setPointerCapture?.(event.pointerId);
  },
  onPointerMove(event) {
    if (!this.dragging || !this.pointer) return;
    const rect = this.svg.getBoundingClientRect();
    const dx = (event.clientX - this.pointer.x) * this.pointer.view.width / rect.width;
    const dy = (event.clientY - this.pointer.y) * this.pointer.view.height / rect.height;
    this.view.x = this.pointer.view.x - dx;
    this.view.y = this.pointer.view.y - dy;
    this.apply();
  },
  onPointerUp() { this.dragging = false; this.pointer = null; $("#canvasWrap").classList.remove("dragging"); },
  apply() {
    if (!this.view) return;
    this.svg.setAttribute("viewBox", `${this.view.x} ${this.view.y} ${this.view.width} ${this.view.height}`);
    const zoom = Math.round(this.svg.clientWidth / this.view.width * 100);
    $("#zoomLabel").textContent = `${zoom}%`;
  }
};

const UIManager = {
  currentCables: [],
  summary: null,
  issues: [],
  init() {
    SvgViewport.init($("#wiringSvg"));
    this.bindStaticEvents();
    WorkflowManager.init();
    this.renderAll(false);
  },
  bindStaticEvents() {
    $$(".sidebar-tab").forEach((button) => button.addEventListener("click", () => this.switchTab(button.dataset.tab)));
    $("#openBtn").addEventListener("click", () => $("#fileInput").click());
    $("#fileInput").addEventListener("change", (event) => this.openFile(event));
    $("#saveBtn").addEventListener("click", () => this.saveJson());
    $("#exportSvgBtn").addEventListener("click", () => this.exportSvg());
    $("#exportPyBtn").addEventListener("click", () => this.exportPython());
    $("#projectName").addEventListener("input", (event) => this.mutate(() => ProjectManager.project.projectName = event.target.value, { sidebar: false }));
    $("#addBlockBtn").addEventListener("click", () => this.addBlock());
    $("#deleteBlockBtn").addEventListener("click", () => this.deleteBlock());
    $("#blockName").addEventListener("change", (event) => this.renameBlock(event.target.value));
    $("#layoutGroup").addEventListener("change", (event) => this.setLayoutGroup(event.target.value));
    $("#addTerminalBtn").addEventListener("click", () => this.addTerminal());
    $("#addConnectionBtn").addEventListener("click", () => this.addConnection());
    $("#blockList").addEventListener("click", (event) => {
      const button = event.target.closest("[data-block-index]");
      if (button) this.selectBlock(Number(button.dataset.blockIndex));
    });
    $("#terminalList").addEventListener("change", (event) => this.handleTerminalChange(event));
    $("#terminalList").addEventListener("click", (event) => this.handleTerminalAction(event));
    $("#connectionList").addEventListener("input", (event) => this.handleConnectionChange(event));
    $("#connectionList").addEventListener("change", (event) => this.handleConnectionChange(event, true));
    $("#connectionList").addEventListener("click", (event) => this.handleConnectionAction(event));
    $("#orphanConnectionList").addEventListener("input", (event) => this.handleConnectionChange(event));
    $("#orphanConnectionList").addEventListener("change", (event) => this.handleConnectionChange(event, true));
    $("#orphanConnectionList").addEventListener("click", (event) => this.handleConnectionAction(event));
    $("#dirDown").addEventListener("click", () => this.setDirection("DOWN"));
    $("#dirUp").addEventListener("click", () => this.setDirection("UP"));
    ["firstDistance", "distanceStep", "textHeight"].forEach((key) => $("#" + key).addEventListener("input", (event) => this.setSetting(key, Number(event.target.value))));
    $("#wiringSvg").addEventListener("click", (event) => {
      const cable = event.target.closest(".cable-group")?.dataset.cable;
      if (cable) this.selectCable(cable);
      else if (!event.target.closest(".terminal-group")) this.selectCable(null);
    });
    $("#zoomOutBtn").addEventListener("click", () => SvgViewport.zoom(1.2));
    $("#zoomInBtn").addEventListener("click", () => SvgViewport.zoom(.82));
    $("#fitBtn").addEventListener("click", () => SvgViewport.fit());
    $("#resetZoomBtn").addEventListener("click", () => SvgViewport.reset100());
    $("#cableMetric").addEventListener("click", () => this.selectCable(null));
  },
  switchTab(name) {
    $$(".sidebar-tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
    $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  },
  mutate(callback, options = {}) {
    callback();
    ProjectManager.markChanged();
    this.renderAll(options.preserveView ?? false, options.sidebar ?? true);
  },
  renderAll(preserveView = false, renderSidebar = true) {
    this.issues = ValidationManager.validate(ProjectManager.project);
    if (renderSidebar) this.renderSidebar();
    this.renderSettings();
    this.renderDiagram(preserveView);
    this.renderIssues();
    $("#projectName").value = ProjectManager.project.projectName;
    $("#saveState").textContent = ProjectManager.sourceName;
    const errors = this.issues.filter((issue) => issue.type === "error").length;
    $("#validationCount").textContent = errors ? `${errors} 个错误` : this.issues.length ? `${this.issues.length} 个提示` : "数据正常";
  },
  renderSidebar() {
    const project = ProjectManager.project;
    $("#blockList").innerHTML = project.terminalBlocks.length ? project.terminalBlocks.map((block, index) => `<button class="block-item${index === ProjectManager.activeBlockIndex ? " active" : ""}" data-block-index="${index}" type="button"><strong>${escapeHtml(block.name)}</strong><span>${block.terminals.length} 个端子${block.layoutGroup ? `<small>${escapeHtml(block.layoutGroup)}</small>` : ""}</span></button>`).join("") : `<div class="issue-ok">暂无端子排，请点击右上角“＋”新增。</div>`;
    const block = ProjectManager.activeBlock;
    $("#blockName").value = block?.name || "";
    $("#blockName").disabled = !block;
    $("#layoutGroup").value = block?.layoutGroup || "";
    $("#layoutGroup").disabled = !block;
    $("#deleteBlockBtn").disabled = !block;
    $("#addTerminalBtn").disabled = !block;
    $("#terminalList").innerHTML = block ? block.terminals.map((terminal, index) => `<div class="terminal-row" data-terminal-index="${index}"><span class="grip">⋮⋮</span><input value="${escapeHtml(terminal.number)}" aria-label="端子号 ${index + 1}"><button data-action="up" type="button" title="上移">↑</button><button data-action="down" type="button" title="下移">↓</button><button class="remove" data-action="remove" type="button" title="删除">×</button></div>`).join("") : "";
    this.renderConnections();
  },
  renderConnections() {
    const project = ProjectManager.project;
    const block = ProjectManager.activeBlock;
    const knownNames = new Set(project.terminalBlocks.map((item) => item.name));
    const entries = project.connections.map((connection, index) => ({ connection, index }));
    const own = entries.filter((entry) => block && entry.connection.terminalBlock === block.name);
    const orphans = entries.filter((entry) => !knownNames.has(entry.connection.terminalBlock));
    $("#connectionList").innerHTML = own.length
      ? own.map(({ connection, index }, displayIndex) => this.connectionCard(connection, index, displayIndex, block)).join("")
      : `<div class="issue-ok">当前端子排暂无接线点。</div>`;
    $("#orphanConnections").hidden = !orphans.length;
    $("#orphanCount").textContent = orphans.length;
    $("#orphanConnectionList").innerHTML = orphans.map(({ connection, index }, displayIndex) => this.connectionCard(connection, index, displayIndex, null)).join("");
  },
  connectionCard(connection, index, displayIndex, block) {
    const invalid = !ValidationManager.isConnectionDrawable(ProjectManager.project, connection);
    const terminals = block?.terminals || [];
    const known = terminals.some((terminal) => terminal.number === connection.terminal);
    const options = terminals.map((terminal) => `<option value="${escapeHtml(terminal.number)}"${terminal.number === connection.terminal ? " selected" : ""}>${escapeHtml(terminal.number)}</option>`).join("");
    const unknown = connection.terminal && !known ? `<option value="${escapeHtml(connection.terminal)}" selected>${escapeHtml(connection.terminal)}（不存在）</option>` : "";
    const terminalField = block
      ? `<label>端子<select data-field="terminal">${unknown}${options}</select></label>`
      : `<label>端子<input data-field="terminal" value="${escapeHtml(connection.terminal)}"></label>`;
    const blockField = block ? "" : `<div class="row"><label class="full">端子排（当前项目中不存在）<input data-field="terminalBlock" value="${escapeHtml(connection.terminalBlock)}"></label></div>`;
    return `<div class="connection-card${invalid ? " invalid" : ""}" data-connection-index="${index}">
        <div class="card-title"><span>接线点 ${displayIndex + 1}</span><button class="remove-connection" data-action="remove" type="button">删除</button></div>
        ${blockField}
        <div class="row">${terminalField}<label>原理号<input data-field="principle" value="${escapeHtml(connection.principle)}"></label></div>
        <div class="row"><label>电缆号<input data-field="cableNumber" value="${escapeHtml(connection.cableNumber)}"></label><label>规格<input data-field="cableSpec" value="${escapeHtml(connection.cableSpec)}"></label></div>
        <div class="row"><label class="full">起点柜<input data-field="fromCabinet" value="${escapeHtml(connection.fromCabinet)}"></label></div>
        <div class="row"><label class="full">去向<input data-field="toCabinet" value="${escapeHtml(connection.toCabinet)}"></label></div>
      </div>`;
  },
  renderSettings() {
    const settings = ProjectManager.project.settings;
    $("#dirDown").classList.toggle("active", settings.direction === "DOWN");
    $("#dirUp").classList.toggle("active", settings.direction === "UP");
    ["firstDistance", "distanceStep", "textHeight"].forEach((key) => {
      $("#" + key).value = settings[key];
      $("#" + key + "Value").textContent = settings[key];
    });
  },
  renderDiagram(preserveView) {
    const block = ProjectManager.activeBlock;
    const blocks = ProjectManager.activeBlocks;
    const viewName = ProjectManager.activeViewName;
    const terminalCount = blocks.reduce((sum, item) => sum + item.terminals.length, 0);
    const svg = $("#wiringSvg");
    $("#activeBlockName").textContent = viewName || "—";
    $("#stageTitle").textContent = block ? `${viewName} 接线预览` : "端子排接线预览";
    if (!block || !terminalCount) {
      svg.innerHTML = "";
      $("#emptyState").hidden = false;
      this.currentCables = [];
      this.summary = CableAnalyzer.summarize([]);
      this.renderStats();
      this.renderInspector();
      return;
    }
    $("#emptyState").hidden = true;
    const geometry = TerminalRenderer.createGeometry(ProjectManager.project, blocks);
    this.currentCables = CableAnalyzer.build(ProjectManager.project, blocks, geometry);
    if (ProjectManager.selectedCable && !this.currentCables.some((cable) => cable.number === ProjectManager.selectedCable)) ProjectManager.selectedCable = null;
    this.summary = CableAnalyzer.summarize(this.currentCables);
    const connectionByTerminal = new Map();
    ProjectManager.project.connections.filter((connection) => connectionBelongsToBlocks(connection, blocks) && connection.principle).forEach((c) => {
      const key = `${c.terminalBlock}\u0000${c.terminal}`;
      if (!connectionByTerminal.has(key)) connectionByTerminal.set(key, c.principle);
    });
    const directionText = geometry.direction === "DOWN" ? "向下接线" : "向上接线";
    svg.innerHTML = `<rect class="svg-frame" x="18" y="18" width="${geometry.sceneWidth - 36}" height="${geometry.sceneHeight - 36}"/>
      <path d="M 34 68 H ${geometry.sceneWidth - 34}" stroke="#d2dada" stroke-width="1"/>
      <text class="svg-title" x="40" y="48" font-size="14">${escapeHtml(ProjectManager.project.projectName)} · ${escapeHtml(viewName)}</text>
      <text class="svg-subtitle" x="${geometry.sceneWidth - 40}" y="48" font-size="9" text-anchor="end">${directionText} / 最左接线端子递增 / ${blocks.length} BLOCKS / ${terminalCount} TERMINALS / ${this.currentCables.length} CABLES</text>
      ${CableRenderer.markup(this.currentCables, geometry, ProjectManager.selectedCable)}
      ${TerminalRenderer.terminalMarkup(geometry, connectionByTerminal)}
      <text class="svg-subtitle" x="40" y="${geometry.sceneHeight - 34}" font-size="8">TERMINAL WIRING PREVIEW · LEFTMOST CONNECTION FIRST</text>`;
    SvgViewport.setScene(geometry.sceneWidth, geometry.sceneHeight, preserveView);
    this.renderStats();
    this.renderInspector();
  },
  renderStats() {
    const summary = this.summary || CableAnalyzer.summarize([]);
    $("#cableCount").textContent = summary.cableCount;
    $("#connectionCount").textContent = summary.connectionCount;
    $("#terminalCount").textContent = ProjectManager.activeBlocks.reduce((sum, block) => sum + block.terminals.length, 0);
    $("#directionValue").textContent = ProjectManager.project.settings.direction === "DOWN" ? "向下" : "向上";
  },
  renderInspector() {
    const cable = this.currentCables.find((item) => item.number === ProjectManager.selectedCable);
    if (!cable) {
      $("#cableInspector").innerHTML = `<div class="no-selection"><span class="wire-symbol"></span><strong>选择一根电缆</strong><span>点击预览中的线路或电缆标签，查看接线点、去向和规格。</span></div>`;
      return;
    }
    $("#cableInspector").innerHTML = `<div class="cable-title"><strong>${escapeHtml(cable.number)}</strong><span>${cable.points.length} 个接线点 · 第 ${cable.index + 1} 层</span></div>
      <div class="info-grid">
        <div class="info-cell"><span>规格</span><strong title="${escapeHtml(cable.spec)}">${escapeHtml(cable.spec)}</strong></div>
        <div class="info-cell"><span>最左端子</span><strong>${escapeHtml(cable.leftmostReference)}</strong></div>
        <div class="info-cell full"><span>去向</span><strong title="${escapeHtml(cable.destination)}">${escapeHtml(cable.destination)}</strong></div>
        <div class="info-cell full"><span>起点柜</span><strong title="${escapeHtml(cable.origin)}">${escapeHtml(cable.origin)}</strong></div>
      </div>
      <div class="point-list"><span>接线点</span>${cable.points.map((point) => `<div class="point-item"><strong>${escapeHtml(point.connection.terminalBlock)}-${escapeHtml(point.connection.terminal)}</strong><span>${escapeHtml(point.connection.principle || "—")}</span></div>`).join("")}</div>`;
  },
  renderIssues() {
    const activeNames = new Set(ProjectManager.activeBlocks.map((block) => block.name));
    const knownNames = new Set(ProjectManager.project.terminalBlocks.map((block) => block.name));
    // 端子排根本不存在的问题不属于任何一块端子排，必须始终显示，否则用户看不到也改不了。
    const visibleIssues = this.issues.filter((issue) => !issue.block || activeNames.has(issue.block) || !knownNames.has(issue.block));
    $("#issueBadge").textContent = visibleIssues.length;
    $("#issueList").innerHTML = visibleIssues.length ? visibleIssues.map((issue) => `<div class="issue ${issue.type}"><strong>${issue.type === "error" ? "错误" : "警告"}：</strong>${escapeHtml(issue.text)}</div>`).join("") : `<div class="issue-ok">当前端子排数据检查通过</div>`;
  },
  selectBlock(index) {
    ProjectManager.activeBlockIndex = index;
    ProjectManager.selectedCable = null;
    this.renderAll(false);
  },
  selectCable(number) {
    ProjectManager.selectedCable = number;
    this.renderDiagram(true);
  },
  addBlock() {
    const names = new Set(ProjectManager.project.terminalBlocks.map((block) => block.name));
    let counter = ProjectManager.project.terminalBlocks.length + 1;
    let name = `端子排${counter}`;
    while (names.has(name)) name = `端子排${++counter}`;
    this.mutate(() => {
      ProjectManager.project.terminalBlocks.push({ name, layoutGroup: "", terminals: [{ number: "1" }] });
      ProjectManager.activeBlockIndex = ProjectManager.project.terminalBlocks.length - 1;
      ProjectManager.selectedCable = null;
    });
  },
  deleteBlock() {
    const block = ProjectManager.activeBlock;
    if (!block || !confirm(`删除端子排“${block.name}”及其全部接线数据？`)) return;
    this.mutate(() => {
      ProjectManager.project.terminalBlocks.splice(ProjectManager.activeBlockIndex, 1);
      ProjectManager.project.connections = ProjectManager.project.connections.filter((connection) => !blockContainsConnection(block, connection));
      ProjectManager.activeBlockIndex = Math.max(0, ProjectManager.activeBlockIndex - 1);
      ProjectManager.selectedCable = null;
    });
  },
  renameBlock(value) {
    const block = ProjectManager.activeBlock;
    const next = value.trim();
    if (!block || !next) { this.renderSidebar(); return; }
    const old = block.name;
    const terminalNumbers = new Set(block.terminals.map((terminal) => terminal.number));
    this.mutate(() => {
      block.name = next;
      ProjectManager.project.connections.forEach((connection) => { if (connection.terminalBlock === old && terminalNumbers.has(connection.terminal)) connection.terminalBlock = next; });
    });
  },
  setLayoutGroup(value) {
    const block = ProjectManager.activeBlock;
    if (!block) return;
    this.mutate(() => { block.layoutGroup = value.trim(); });
  },
  addTerminal() {
    const block = ProjectManager.activeBlock;
    if (!block) return;
    const numbers = new Set(block.terminals.map((terminal) => terminal.number));
    let number = 1;
    while (numbers.has(String(number))) number++;
    this.mutate(() => block.terminals.push({ number: String(number) }));
  },
  handleTerminalChange(event) {
    const row = event.target.closest("[data-terminal-index]");
    if (!row || event.target.tagName !== "INPUT") return;
    const block = ProjectManager.activeBlock;
    const terminal = block.terminals[Number(row.dataset.terminalIndex)];
    const old = terminal.number;
    const next = event.target.value.trim();
    this.mutate(() => {
      terminal.number = next;
      ProjectManager.project.connections.forEach((connection) => { if (connection.terminalBlock === block.name && connection.terminal === old) connection.terminal = next; });
    });
  },
  handleTerminalAction(event) {
    const button = event.target.closest("button[data-action]");
    const row = event.target.closest("[data-terminal-index]");
    if (!button || !row) return;
    const index = Number(row.dataset.terminalIndex);
    const block = ProjectManager.activeBlock;
    this.mutate(() => {
      if (button.dataset.action === "up" && index > 0) [block.terminals[index - 1], block.terminals[index]] = [block.terminals[index], block.terminals[index - 1]];
      if (button.dataset.action === "down" && index < block.terminals.length - 1) [block.terminals[index + 1], block.terminals[index]] = [block.terminals[index], block.terminals[index + 1]];
      if (button.dataset.action === "remove") block.terminals.splice(index, 1);
    });
  },
  addConnection() {
    const block = ProjectManager.activeBlock;
    if (!block) return;
    this.mutate(() => ProjectManager.project.connections.push({
      terminalBlock: block.name, terminal: block.terminals[0]?.number || "", principle: "", fromCabinet: "", toCabinet: "", cableNumber: "新电缆-01", cableSpec: ""
    }));
    this.switchTab("connections");
  },
  handleConnectionChange(event, finalize = false) {
    const card = event.target.closest("[data-connection-index]");
    const field = event.target.dataset.field;
    if (!card || !field) return;
    const connection = ProjectManager.project.connections[Number(card.dataset.connectionIndex)];
    connection[field] = event.target.value;
    ProjectManager.markChanged();
    // 端子排或端子改动会让这条接线换归属，必须整体重排侧栏；其他字段保持视图和输入焦点。
    if (finalize && (field === "terminalBlock" || field === "terminal")) { this.renderAll(true); return; }
    this.issues = ValidationManager.validate(ProjectManager.project);
    this.renderDiagram(true);
    this.renderIssues();
    $("#saveState").textContent = ProjectManager.sourceName;
    const errors = this.issues.filter((issue) => issue.type === "error").length;
    $("#validationCount").textContent = errors ? `${errors} 个错误` : this.issues.length ? `${this.issues.length} 个提示` : "数据正常";
    const invalid = !ValidationManager.isConnectionDrawable(ProjectManager.project, connection);
    card.classList.toggle("invalid", invalid);
  },
  handleConnectionAction(event) {
    const button = event.target.closest("[data-action='remove']");
    const card = event.target.closest("[data-connection-index]");
    if (!button || !card) return;
    this.mutate(() => ProjectManager.project.connections.splice(Number(card.dataset.connectionIndex), 1));
  },
  setDirection(direction) { this.mutate(() => ProjectManager.project.settings.direction = direction); },
  setSetting(key, value) {
    ProjectManager.project.settings[key] = value;
    ProjectManager.markChanged();
    this.renderSettings();
    this.renderDiagram(true);
    $("#saveState").textContent = ProjectManager.sourceName;
  },
  async openFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      ProjectManager.setProject(JSON.parse(text), file.name);
      this.renderAll(false);
      this.toast(`已打开 ${file.name}`);
    } catch (error) {
      alert(`无法打开 JSON：${error.message}`);
    } finally {
      event.target.value = "";
    }
  },
  saveJson() {
    const content = JSON.stringify(ProjectManager.project, null, 2);
    DataManager.download(content, `${safeFileName(ProjectManager.project.projectName)}.json`, "application/json;charset=utf-8");
    ProjectManager.sourceName = "已导出 JSON";
    $("#saveState").textContent = ProjectManager.sourceName;
    this.toast("当前项目 JSON 已保存");
  },
  exportSvg() {
    const block = ProjectManager.activeBlock;
    if (!block || !$("#wiringSvg").innerHTML) return this.toast("当前没有可导出的图形");
    const width = SvgViewport.scene.width;
    const height = SvgViewport.scene.height;
    // 图纸按 1 个 CAD 单位 = 1mm 折算真实图幅，插入 CAD 或排版软件时尺寸才不会跑掉。
    const source = `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${(width / UNIT_SCALE).toFixed(1)}mm" height="${(height / UNIT_SCALE).toFixed(1)}mm" viewBox="0 0 ${width} ${height}"><style>${this.exportSvgStyles()}</style>${$("#wiringSvg").innerHTML}</svg>`;
    DataManager.download(source, `${safeFileName(ProjectManager.project.projectName)}-${safeFileName(ProjectManager.activeViewName)}.svg`, "image/svg+xml;charset=utf-8");
    this.toast("当前端子排 SVG 已导出");
  },
  exportPython() {
    const blocks = ProjectManager.activeBlocks;
    if (!blocks.length || !blocks.some((block) => block.terminals.length)) return this.toast("当前没有可出图的端子排");
    const viewName = ProjectManager.activeViewName;
    let content;
    try {
      content = PythonExporter.build(ProjectManager.project, blocks, viewName);
    } catch (error) {
      return this.toast(`生成脚本失败：${error.message}`);
    }
    DataManager.download(content, `${safeFileName(ProjectManager.project.projectName)}-${safeFileName(viewName)}-出图.py`, "text/x-python;charset=utf-8");
    const errors = this.issues.filter((issue) => issue.type === "error").length;
    this.toast(errors ? `出图脚本已导出，注意还有 ${errors} 个错误未处理` : "出图脚本已导出，运行它即生成 DXF");
  },
  exportSvgStyles() {
    return `.svg-frame{fill:#fff;stroke:#b8c4c1}.svg-title{fill:#425157;font-family:'Microsoft YaHei UI';font-weight:700}.svg-subtitle{fill:#82908e;font-family:Consolas}.terminal-block-frame rect,.terminal-block-frame line,.terminal-divider{fill:none;stroke:#526368;stroke-width:1}.terminal-hit-area{fill:transparent;stroke:none}.terminal-number,.terminal-block-name,.principle-label{fill:#1e2c31;font-family:Consolas,'Microsoft YaHei UI';text-anchor:middle;dominant-baseline:middle}.terminal-number,.terminal-block-name{font-weight:700}.principle-label{fill:#536167}.cable-line,.cable-chevron{fill:none;stroke:#278394;stroke-width:2}.cable-label-bg{fill:#fff}.cable-label{fill:#1f4f59;font-family:Consolas;font-weight:700}.cable-destination,.cable-spec{fill:#34464b;font-family:'Microsoft YaHei UI'}`;
  },
  toast(message) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  }
};

window.addEventListener("DOMContentLoaded", () => UIManager.init());
