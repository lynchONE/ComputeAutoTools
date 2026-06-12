const form = document.querySelector("#configForm");
const toast = document.querySelector("#toast");
const clock = document.querySelector("#clock");
const languageSelect = document.querySelector("#languageSelect");
const offersList = document.querySelector("#offersList");
const runBadge = document.querySelector("#runBadge");
const scanBadge = document.querySelector("#scanBadge");
const lastScanText = document.querySelector("#lastScanText");
const gpuSearchInput = document.querySelector("#gpuSearchInput");
const gpuModelList = document.querySelector("#gpuModelList");
const selectedGpuList = document.querySelector("#selectedGpuList");
const gpuCategoryTabs = document.querySelector("#gpuCategoryTabs");
const gpuSourceText = document.querySelector("#gpuSourceText");
const resultsSection = document.querySelector("#resultsSection");
const selectedOfferText = document.querySelector("#selectedOfferText");
const offerGpuFilters = document.querySelector("#offerGpuFilters");
const sideEventList = document.querySelector("#sideEventList");
const sideRunText = document.querySelector("#sideRunText");
const instancesList = document.querySelector("#instancesList");
const templateSearchInput = document.querySelector("#templateSearchInput");
const templateList = document.querySelector("#templateList");
const taskList = document.querySelector("#taskList");
const activeTaskPanel = document.querySelector("#activeTaskPanel");
const taskNameInput = document.querySelector("#taskNameInput");
const buttons = {
  scan: document.querySelector("#scanBtn"),
  start: document.querySelector("#startBtn"),
  stop: document.querySelector("#stopBtn"),
  bark: document.querySelector("#barkBtn"),
  refreshTasks: document.querySelector("#refreshTasksBtn"),
  createTask: document.querySelector("#createTaskBtn"),
  updateTask: document.querySelector("#updateTaskBtn"),
  startTask: document.querySelector("#startTaskBtn"),
  stopTask: document.querySelector("#stopTaskBtn"),
  deleteTask: document.querySelector("#deleteTaskBtn"),
  refreshInstances: document.querySelector("#refreshInstancesBtn"),
  cleanupInstances: document.querySelector("#cleanupInstancesBtn"),
  deleteInstances: document.querySelector("#deleteInstancesBtn"),
  templateSearch: document.querySelector("#templateSearchBtn"),
  templatePopular: document.querySelector("#templatePopularBtn"),
  clearEvents: document.querySelector("#clearEventsBtn"),
};

let currentConfig = null;
let busy = false;
let gpuModels = [];
let selectedGpuNames = [];
let selectedOfferIds = [];
let currentStateOffers = [];
let activeGpuCategory = "popular";
let activeOfferGpuCountFilter = null;
let activeTab = "scan";
let templatesLoaded = false;
let selectedInstanceIds = [];
let lastInstancesSignature = "";
let configDirty = false;
let currentLanguage = "zh";
let lastState = null;
let lastTemplates = [];
let lastInstances = [];
let lastGpuPayload = null;
let tasks = [];
let selectedTaskId = null;
let lastProviderValue = "";

const jsonFields = new Set(["create.env_vars"]);
const maxVisibleOffers = 6;
const gpuCategories = [
  { id: "popular", label: "热门", match: (name) => modelRank(name) >= 40 },
  { id: "datacenter", label: "数据中心", match: (name) => /^(B200|B300|H200|H100|A100|A800|L40S|L40|L4)/.test(name) },
  { id: "rtx50", label: "RTX 50", match: (name) => /^RTX 5/.test(name) },
  { id: "rtx40", label: "RTX 40", match: (name) => /^RTX 4/.test(name) },
  { id: "rtx30", label: "RTX 30", match: (name) => /^RTX 30|^RTX 31|^RTX 32/.test(name) },
  { id: "pro", label: "工作站", match: (name) => /RTX PRO|RTX A|Quadro|Q RTX/.test(name) },
  { id: "legacy", label: "旧型号", match: (name) => /GTX|Tesla|P100|P40|P4|T4|V100/.test(name) },
  { id: "all", label: "全部", match: () => true },
];

const i18n = {
  zh: {
    title: "Compute · 算力终端",
    brandSub: "算力终端",
    language: "语言",
    saveConfig: "保存",
    manualScan: "手动扫描",
    startMonitor: "启动监控",
    stopMonitor: "停止监控",
    testBark: "测试 Bark",
    gpuLoading: "GPU 型号加载中",
    gpuSourceVast: "来自 Vast 当前可租报价",
    gpuSourceFallback: "使用内置型号列表",
    gpuSourceCount: "{count} 个型号，{source}",
    instancesLoading: "实例加载中",
    cleanedInstances: "已处理 {count} 个错误实例",
    deleteNeedSelection: "请先勾选要删除的实例",
    deleteSubmitted: "已提交删除 {count} 个实例",
    templatesLoading: "模板加载中",
    noGpuLimit: "未限制 GPU 型号",
    noGpuMatches: "没有匹配的 GPU 型号",
    offerCount: "{count} 个报价",
    selectable: "可选",
    familyDatacenter: "数据中心",
    familyWorkstation: "工作站",
    familyLegacy: "旧型号",
    familyOther: "其他",
    monitorRunning: "监控中",
    notRunning: "未运行",
    scanning: "扫描中",
    idle: "空闲",
    lastScan: "上次扫描 {time}",
    notScanned: "未扫描",
    noOffers: "暂无候选机器",
    noOffersForGpuCount: "当前 GPU 数量下暂无候选机器",
    selectOfferAria: "选择 Rank {rank}，{gpus}x {gpuName}，offer {offerId}",
    hourlyPrice: "$/小时",
    totalTflops: "总 TFLOPS",
    reliability: "可靠性",
    gpuRam: "显存 GB",
    region: "地区",
    all: "全部",
    gpuCards: "{count} 卡",
    selectedOfferDefault: "未指定候选机器时，会按排序从上往下自动创建",
    selectedOffer: "已指定自动创建：{gpus}x {gpuName} #{offerId}",
    selectedOfferMissing: "已指定 offer #{offerId}，下次扫描仍会校验它是否符合条件",
    noCreatedRecords: "还没有创建记录。启动监控后，创建和连接检测进度会显示在这里。",
    deleted: "已删除",
    deleteFailed: "删除失败",
    deleting: "删除中",
    sshChecking: "SSH 检测中",
    connectionPassed: "连接通过",
    connectionChecking: "连接检测中",
    unverifiedKept: "未验证保留",
    kept: "保留",
    checking: "检测中",
    noEvents: "暂无运行事件",
    sideRunning: "监控运行中",
    sideStopped: "监控未启动",
    noSideLogs: "暂无运行日志",
    noAccountInstances: "账号当前没有实例，或平台 API 没有返回实例。",
    choose: "选择",
    label: "标签",
    price: "价格",
    statusDetail: "状态详情",
    noTemplates: "没有匹配的模板",
    unnamedTemplate: "未命名模板",
    recommended: "推荐",
    template: "模板",
    createdTimes: "{count} 次创建",
    templateSelected: "已选择模板：{name}",
    statusErrorPrefix: "错误: {message}",
    statusConflict: "异常: loading / stopped",
    statusError: "错误",
    configSaved: "配置已保存",
    scanDone: "扫描完成",
    monitorStarted: "监控已启动",
    monitorStopped: "监控已停止",
    barkSent: "测试通知已发送",
    instancesRefreshed: "实例已刷新",
    errorInstancesCleaned: "错误实例已清理",
    selectedInstancesDeleted: "选中实例已删除",
    configDirty: "配置修改后需要保存",
    tasksRefreshed: "任务已刷新",
    taskCreated: "任务已创建",
    taskUpdated: "任务已更新",
    taskStarted: "任务已启动",
    taskStopped: "任务已停止",
    taskDeleted: "任务已删除",
    eventsCleared: "日志已清空",
    noTasks: "还没有监控任务",
    noActiveTask: "当前没有运行中的监控任务",
    selectTaskFirst: "请先选择任务",
    taskNameRequired: "请填写任务名称",
    activeTask: "运行中任务",
    taskList: "任务列表",
    taskStatus: "状态",
    taskPlatform: "平台",
    taskGpu: "GPU",
    taskPrice: "最高价格",
    taskCreateLimit: "创建上限",
    taskInterval: "扫描间隔",
    taskUpdatedAt: "更新时间",
    taskLastScan: "上次扫描",
    taskNextScan: "下次扫描",
    taskAutoCreate: "自动创建",
    taskStockAlert: "库存告警",
    enabled: "开启",
    disabled: "关闭",
    eventInfo: "信息",
    eventSuccess: "成功",
    eventWarn: "警告",
    eventError: "错误",
  },
  en: {
    title: "Compute · Compute Terminal",
    brandSub: "Compute Terminal",
    language: "Language",
    saveConfig: "Save",
    manualScan: "Scan Now",
    startMonitor: "Start Monitor",
    stopMonitor: "Stop Monitor",
    testBark: "Test Bark",
    gpuLoading: "Loading GPU models",
    gpuSourceVast: "from current Vast rentable offers",
    gpuSourceFallback: "using built-in GPU model list",
    gpuSourceCount: "{count} models, {source}",
    instancesLoading: "Loading instances",
    cleanedInstances: "Processed {count} error instances",
    deleteNeedSelection: "Select instances to delete first",
    deleteSubmitted: "Submitted deletion for {count} instances",
    templatesLoading: "Loading templates",
    noGpuLimit: "No GPU model limit",
    noGpuMatches: "No matching GPU models",
    offerCount: "{count} offers",
    selectable: "Selectable",
    familyDatacenter: "Datacenter",
    familyWorkstation: "Workstation",
    familyLegacy: "Legacy",
    familyOther: "Other",
    monitorRunning: "Monitoring",
    notRunning: "Stopped",
    scanning: "Scanning",
    idle: "Idle",
    lastScan: "Last scan {time}",
    notScanned: "Not scanned",
    noOffers: "No candidate offers",
    noOffersForGpuCount: "No candidates for this GPU count",
    selectOfferAria: "Select Rank {rank}, {gpus}x {gpuName}, offer {offerId}",
    hourlyPrice: "$/hour",
    totalTflops: "Total TFLOPS",
    reliability: "Reliability",
    gpuRam: "VRAM GB",
    region: "Region",
    all: "All",
    gpuCards: "{count} GPUs",
    selectedOfferDefault: "When no candidate is selected, auto-create uses the sorted order from top to bottom",
    selectedOffer: "Auto-create target: {gpus}x {gpuName} #{offerId}",
    selectedOfferMissing: "Offer #{offerId} is selected; next scan will still verify it matches filters",
    noCreatedRecords: "No create records yet. After monitoring starts, creation and connection checks appear here.",
    deleted: "Deleted",
    deleteFailed: "Delete failed",
    deleting: "Deleting",
    sshChecking: "Checking SSH",
    connectionPassed: "Connection passed",
    connectionChecking: "Checking connection",
    unverifiedKept: "Kept unverified",
    kept: "Kept",
    checking: "Checking",
    noEvents: "No runtime events",
    sideRunning: "Monitor running",
    sideStopped: "Monitor stopped",
    noSideLogs: "No runtime logs",
    noAccountInstances: "No instances in the account, or the platform API returned none.",
    choose: "Select",
    label: "Label",
    price: "Price",
    statusDetail: "Status detail",
    noTemplates: "No matching templates",
    unnamedTemplate: "Unnamed template",
    recommended: "Recommended",
    template: "Template",
    createdTimes: "{count} creates",
    templateSelected: "Template selected: {name}",
    statusErrorPrefix: "Error: {message}",
    statusConflict: "Abnormal: loading / stopped",
    statusError: "Error",
    configSaved: "Config saved",
    scanDone: "Scan completed",
    monitorStarted: "Monitor started",
    monitorStopped: "Monitor stopped",
    barkSent: "Test notification sent",
    instancesRefreshed: "Instances refreshed",
    errorInstancesCleaned: "Error instances cleaned",
    selectedInstancesDeleted: "Selected instances deleted",
    configDirty: "Config changed; save to apply",
    tasksRefreshed: "Tasks refreshed",
    taskCreated: "Task created",
    taskUpdated: "Task updated",
    taskStarted: "Task started",
    taskStopped: "Task stopped",
    taskDeleted: "Task deleted",
    eventsCleared: "Logs cleared",
    noTasks: "No monitor tasks yet",
    noActiveTask: "No monitor task is running",
    selectTaskFirst: "Select a task first",
    taskNameRequired: "Task name is required",
    activeTask: "Running Task",
    taskList: "Tasks",
    taskStatus: "Status",
    taskPlatform: "Platform",
    taskGpu: "GPU",
    taskPrice: "Max Price",
    taskCreateLimit: "Create Limit",
    taskInterval: "Scan Interval",
    taskUpdatedAt: "Updated",
    taskLastScan: "Last Scan",
    taskNextScan: "Next Scan",
    taskAutoCreate: "Auto Create",
    taskStockAlert: "Stock Alert",
    enabled: "Enabled",
    disabled: "Disabled",
    eventInfo: "info",
    eventSuccess: "success",
    eventWarn: "warn",
    eventError: "error",
  },
};

const staticTextPairs = [
  ["算力终端", "Compute Terminal"],
  ["扫描筛选", "Scan Filters"],
  ["连接通知", "Connect"],
  ["运行中任务", "Running Tasks"],
  ["账号实例", "Instances"],
  ["未运行", "Stopped"],
  ["空闲", "Idle"],
  ["报价扫描 / 自动租用", "Offer Scan / Auto Rent"],
  ["未扫描", "Not scanned"],
  ["语言", "Language"],
  ["中文", "中文"],
  ["保存", "Save"],
  ["扫描监控", "Scan Monitor"],
  ["保存配置后，可以手动扫描或启动自动监控", "After saving, scan manually or start automatic monitoring"],
  ["手动扫描", "Scan Now"],
  ["启动监控", "Start Monitor"],
  ["停止监控", "Stop Monitor"],
  ["平台", "Platform"],
  ["GPU 型号", "GPU Models"],
  ["GPU 型号加载中", "Loading GPU models"],
  ["搜索型号", "Search Models"],
  ["扫描条件", "Scan Filters"],
  ["最少 GPU 数", "Min GPUs"],
  ["最多 GPU 数", "Max GPUs"],
  ["最高 $/小时", "Max $/hour"],
  ["最低显存 GB", "Min VRAM GB"],
  ["最低总 TFLOPS", "Min Total TFLOPS"],
  ["最低 TFLOPS/USD", "Min TFLOPS/USD"],
  ["最低可靠性", "Min Reliability"],
  ["搜索上限", "Search Limit"],
  ["报价类型", "Offer Type"],
  ["排序", "Sort"],
  ["价格最低", "Lowest Price"],
  ["总 TFLOPS", "Total TFLOPS"],
  ["可靠性", "Reliability"],
  ["计价磁盘 GB", "Pricing Disk GB"],
  ["不限", "No Limit"],
  ["必须是", "Must Be"],
  ["必须不是", "Must Not Be"],
  ["只要 verified", "Verified only"],
  ["允许 external", "Allow external"],
  ["库存下降告警", "Stock Drop Alert"],
  ["按当前扫描条件统计可租机器数量", "Count rentable machines using current scan filters"],
  ["启用库存告警", "Enable stock alerts"],
  ["告警窗口 分钟", "Alert Window Min"],
  ["最少基线数量", "Min Baseline"],
  ["减少台数阈值", "Drop Count"],
  ["减少百分比", "Drop Percent"],
  ["冷却 分钟", "Cooldown Min"],
  ["自动创建配置", "Auto-Create Config"],
  ["未指定候选机器时，会按排序从上往下自动创建", "When no candidate is selected, auto-create uses the sorted order from top to bottom"],
  ["命中后自动创建", "Auto-create matches"],
  ["不可用时取消", "Cancel unavailable"],
  ["允许无 SSH 创建", "Allow no-SSH create"],
  [
    "未配置 SSH 时默认不会自动创建。打开无 SSH 创建后，如果机器无法正常启动或无法连接，平台可能已经开始计费，风险由用户承担。",
    "Auto-create is blocked by default when SSH is not configured. If no-SSH create is enabled and the machine cannot start or connect, the platform may already charge you and you accept that risk.",
  ],
  ["Template 搜索", "Template Search"],
  ["搜索模板", "Search Templates"],
  ["推荐模板", "Popular Templates"],
  ["磁盘 GB", "Disk GB"],
  ["标签前缀", "Label Prefix"],
  ["最多创建数量", "Max Created"],
  ["每轮最多创建", "Max Per Cycle"],
  ["运行类型", "Run Type"],
  ["可留空", "Optional"],
  ["如 -p 7860:7860", "e.g. -p 7860:7860"],
  ["扫描结果", "Scan Results"],
  ["手动扫描或定时扫描后，候选机器会直接显示在这里", "Candidate machines appear here after manual or scheduled scans"],
  ["运行日志", "Runtime Logs"],
  ["清空", "Clear"],
  ["等待监控", "Waiting"],
  ["连接测试与通知", "Connection Test and Notifications"],
  [
    "实例创建后会使用下方私钥真实 SSH 登录并执行命令；未填写私钥时默认不会自动创建，除非在自动创建配置中允许无 SSH 创建并自行承担计费风险。",
    "After an instance is created, the private key below is used for a real SSH login and command execution; without a key, auto-create is blocked by default unless no-SSH create is enabled and billing risk is accepted.",
  ],
  ["账号与 Bark", "Account and Bark"],
  ["测试 Bark", "Test Bark"],
  ["SSH 与调度", "SSH and Schedule"],
  ["测试模式", "Test Mode"],
  ["SSH 登录命令", "SSH login command"],
  ["SSH 用户", "SSH User"],
  ["私钥路径", "Private Key Path"],
  ["必填，如 C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519", "Required, e.g. C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519"],
  ["SSH 命令", "SSH Command"],
  ["等待超时 秒", "Wait Timeout Sec"],
  ["轮询间隔 秒", "Poll Interval Sec"],
  ["连接超时 秒", "Connect Timeout Sec"],
  ["扫描间隔 秒", "Scan Interval Sec"],
  ["错误时 Bark 通知", "Bark notify on error"],
  ["查看、创建、修改、启动和删除监控任务", "View, create, edit, start, and delete monitor tasks"],
  ["刷新任务", "Refresh Tasks"],
  ["任务名称", "Task Name"],
  ["如 H100 自动创建", "e.g. H100 Auto Create"],
  ["新建任务", "Create Task"],
  ["更新任务", "Update Task"],
  ["启动任务", "Start Task"],
  ["停止任务", "Stop Task"],
  ["删除任务", "Delete Task"],
  ["读取当前账号已有实例", "Read existing instances in the current account"],
  ["清理错误实例", "Clean Error Instances"],
  ["删除选中", "Delete Selected"],
  ["刷新实例", "Refresh Instances"],
  ["热门", "Popular"],
  ["数据中心", "Datacenter"],
  ["工作站", "Workstation"],
  ["旧型号", "Legacy"],
  ["全部", "All"],
  ["其他", "Other"],
  ["未限制 GPU 型号", "No GPU model limit"],
  ["没有匹配的 GPU 型号", "No matching GPU models"],
  ["暂无候选机器", "No candidate offers"],
  ["当前 GPU 数量下暂无候选机器", "No candidates for this GPU count"],
  ["还没有创建记录。启动监控后，创建和连接检测进度会显示在这里。", "No create records yet. After monitoring starts, creation and connection checks appear here."],
  ["暂无运行事件", "No runtime events"],
  ["监控运行中", "Monitor running"],
  ["监控未启动", "Monitor stopped"],
  ["暂无运行日志", "No runtime logs"],
  ["账号当前没有实例，或平台 API 没有返回实例。", "No instances in the account, or the platform API returned none."],
  ["选择", "Select"],
  ["标签", "Label"],
  ["价格", "Price"],
  ["地区", "Region"],
  ["状态详情", "Status Detail"],
  ["没有匹配的模板", "No matching templates"],
  ["未命名模板", "Unnamed template"],
  ["推荐", "Recommended"],
  ["模板", "Template"],
];

const zhToEnText = new Map(staticTextPairs);
zhToEnText.set("Private Key Path", "Private Key Path");
zhToEnText.set("Private Key Content", "Private Key Content");
const enToZhText = new Map(staticTextPairs.map(([zh, en]) => [en, zh]));
enToZhText.set("Private Key Path", "Private Key Path");
enToZhText.set("Private Key Content", "Private Key Content");

const placeholderPairs = [
  ["必填，如 C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519", "Required, e.g. C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519"],
  ["可留空", "Optional"],
  ["如 -p 7860:7860", "e.g. -p 7860:7860"],
  ["如 H100 自动创建", "e.g. H100 Auto Create"],
];
const zhToEnPlaceholder = new Map(placeholderPairs);
zhToEnPlaceholder.set(
  "Optional, e.g. C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519",
  "Optional, e.g. C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519",
);
const enToZhPlaceholder = new Map(placeholderPairs.map(([zh, en]) => [en, zh]));
enToZhPlaceholder.set(
  "Optional, e.g. C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519",
  "Optional, e.g. C:\\\\Users\\\\Administrator\\\\.ssh\\\\id_ed25519",
);

function t(key, vars = {}) {
  const value = i18n[currentLanguage][key];
  if (typeof value !== "string") return key;
  return value.replace(/\{(\w+)\}/g, (match, name) => {
    if (!Object.prototype.hasOwnProperty.call(vars, name)) return match;
    return String(vars[name]);
  });
}

function applyLanguage(language) {
  currentLanguage = language === "en" ? "en" : "zh";
  document.documentElement.lang = currentLanguage === "en" ? "en" : "zh-CN";
  document.title = t("title");
  const languageInput = form.elements["ui.language"];
  if (languageInput) languageInput.value = currentLanguage;
  if (languageSelect) languageSelect.value = currentLanguage;
  translateStaticText(document.body);
  translateAttributes();
}

function translateStaticText(root) {
  const map = currentLanguage === "en" ? zhToEnText : enToZhText;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (["SCRIPT", "STYLE", "TEXTAREA"].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const original = node.nodeValue;
    const trimmed = original.trim();
    if (!trimmed || !map.has(trimmed)) continue;
    node.nodeValue = original.replace(trimmed, map.get(trimmed));
  }
}

function translateAttributes() {
  const placeholderMap = currentLanguage === "en" ? zhToEnPlaceholder : enToZhPlaceholder;
  document.querySelectorAll("[placeholder]").forEach((element) => {
    const value = element.getAttribute("placeholder");
    if (placeholderMap.has(value)) element.setAttribute("placeholder", placeholderMap.get(value));
  });
}

function phrase(value) {
  if (currentLanguage === "en") return zhToEnText.get(value) || value;
  return enToZhText.get(value) || value;
}

function translateMessage(message) {
  const text = String(message);
  if (currentLanguage === "en") return translateChineseMessageToEnglish(text);
  const exact = {
    "Monitor started": "监控已启动",
    "Monitor stopped": "监控已停止",
    "Config saved": "配置已保存",
    "Auto-create target offer updated": "自动创建目标已更新",
    "Bark URL is empty": "Bark URL 为空",
    "Bark test notification sent": "Bark 测试通知已发送",
    "Scan completed with no matching offers": "扫描完成，没有匹配报价",
    "SSH private key path is required before auto-create can verify login": "自动创建前必须填写 SSH 私钥路径用于验证登录",
    "SSH private key path or private key is required before auto-create can verify login": "自动创建前必须填写 SSH 私钥路径或私钥内容用于验证登录",
    "Creating without SSH verification; if the machine cannot start or connect, charges may still accrue and the user accepts this risk": "已允许无 SSH 创建；如果机器无法正常启动或无法连接，平台可能仍会计费，风险由用户承担",
    "SSH private key is not configured; skipped SSH recheck for unverified instances, and no-SSH created instances remain billable at the user's risk": "未配置 SSH 私钥，已跳过未验证实例的 SSH 复检；无 SSH 创建的实例将保留，计费风险由用户承担",
    "Managed instance limit reached, skipping create": "已达到托管实例数量上限，跳过创建",
    "Managed instance limit reached, stopping monitor": "已达到托管实例数量上限，停止监控",
    "Selected auto-create offer is no longer in scan results": "选中的自动创建 offer 已不在扫描结果中",
    "Offers matched, but no instance was created": "已命中 offer，但没有实例创建成功",
    "Ready notification failed": "就绪通知发送失败",
    "Monitor scan failed": "监控扫描失败",
    "Error notification failed": "错误通知发送失败",
    "Stock drop notification skipped; Bark URL is empty": "库存下降通知已跳过：Bark URL 为空",
    "Stock drop notification sent": "库存下降通知已发送",
    "Stock drop notification failed": "库存下降通知发送失败",
    "Vast GPU model lookup failed": "Vast GPU 型号查询失败",
    "HTTP request failed": "HTTP 请求失败",
    "A scan is already in progress": "已有扫描正在进行",
    "Vast API Key is empty; cannot call Vast SDK": "Vast API Key 为空，无法调用 Vast SDK",
    "RunPod provider is not implemented yet": "RunPod 平台适配器尚未实现",
    "Vast API Key is required before enabling auto create": "启用自动创建前必须填写 Vast API Key",
    "Docker image or template_hash is required before enabling auto create": "启用自动创建前必须填写 Docker Image 或 Template Hash",
    "label_prefix is required before enabling auto create": "启用自动创建前必须填写标签前缀",
    "ssh private key path is required": "必须填写 SSH 私钥路径",
    "ssh private key path or private key is required": "必须填写 SSH 私钥路径或私钥内容",
  };
  if (exact[text]) return exact[text];
  const patterns = [
    [/^Scan matched (\d+) candidate offers$/, "扫描命中 {1} 个候选机器"],
    [/^(.+) stock dropped quickly: (\d+) -> (\d+), down (\d+) offers \(([\d.]+)%\)$/, "{1} 库存快速下降：{2} -> {3}，减少 {4} 台（{5}%）"],
    [/^Create failed for offer (\d+)$/, "offer {1} 创建失败"],
    [/^Instance (\d+) created; checking connection$/, "实例 {1} 已创建，正在检测 SSH"],
    [/^Instance (\d+) was created without SSH verification; if it cannot start or connect, charges may still accrue and the user accepts this risk$/, "实例 {1} 已创建但未配置 SSH 验证；如果实例无法正常启动或无法连接，可能仍会计费，风险由用户承担"],
    [/^Connection test failed for instance (\d+); deleting instance$/, "实例 {1} SSH 检测失败，正在删除实例"],
    [/^Failed to delete instance (\d+) after connection failure$/, "实例 {1} 连接失败后删除失败"],
    [/^Instance (\d+) deleted after connection failure$/, "实例 {1} 连接失败后已删除"],
    [/^Instance (\d+) connection test passed$/, "实例 {1} SSH 连接检测通过"],
    [/^Instance (\d+) ready notification skipped; Bark URL is empty$/, "实例 {1} 就绪通知已跳过：Bark URL 为空"],
    [/^Instance (\d+) ready notification sent$/, "实例 {1} 就绪通知已发送"],
    [/^Managed instance (\d+) is in error state; deleting instance$/, "托管实例 {1} 处于 error 状态，正在删除"],
    [/^Failed to delete managed error instance (\d+)$/, "托管 error 实例 {1} 删除失败"],
    [/^Managed error instance (\d+) deleted$/, "托管 error 实例 {1} 已删除"],
    [/^Verifying SSH for managed instance (\d+)$/, "正在验证托管实例 {1} 的 SSH"],
    [/^Managed instance (\d+) failed SSH verification; deleting instance$/, "托管实例 {1} SSH 验证失败，正在删除"],
    [/^Failed to delete SSH-failed managed instance (\d+)$/, "SSH 失败的托管实例 {1} 删除失败"],
    [/^Managed instance (\d+) deleted after SSH verification failed$/, "托管实例 {1} SSH 验证失败后已删除"],
    [/^Managed instance (\d+) SSH verification passed$/, "托管实例 {1} SSH 验证通过"],
    [/^Manual deletion requested for instance (\d+)$/, "已请求手动删除实例 {1}"],
    [/^Manual deletion failed for instance (\d+)$/, "实例 {1} 手动删除失败"],
    [/^Manual deletion completed for instance (\d+)$/, "实例 {1} 手动删除完成"],
    [/^ssh private key not found: (.+)$/, "SSH 私钥不存在：{1}"],
    [/^SSH check timed out for instance (\d+): (.+)$/, "实例 {1} SSH 检测超时：{2}"],
  ];
  for (const [pattern, template] of patterns) {
    const match = text.match(pattern);
    if (!match) continue;
    return template.replace(/\{(\d+)\}/g, (_, index) => match[Number(index)] || "");
  }
  return text;
}

function translateChineseMessageToEnglish(text) {
  const exact = {
    "监控已启动": "Monitor started",
    "监控已停止": "Monitor stopped",
    "配置已保存": "Config saved",
    "自动创建目标已更新": "Auto-create target offer updated",
    "Bark URL 为空": "Bark URL is empty",
    "Bark 测试通知已发送": "Bark test notification sent",
    "扫描完成，没有匹配报价": "Scan completed with no matching offers",
    "自动创建前必须填写 SSH 私钥路径用于验证登录": "SSH private key path is required before auto-create can verify login",
    "自动创建前必须填写 SSH 私钥路径或私钥内容用于验证登录": "SSH private key path or private key is required before auto-create can verify login",
    "已允许无 SSH 创建；如果机器无法正常启动或无法连接，平台可能仍会计费，风险由用户承担": "Creating without SSH verification; if the machine cannot start or connect, charges may still accrue and the user accepts this risk",
    "未配置 SSH 私钥，已跳过未验证实例的 SSH 复检；无 SSH 创建的实例将保留，计费风险由用户承担": "SSH private key is not configured; skipped SSH recheck for unverified instances, and no-SSH created instances remain billable at the user's risk",
    "已达到托管实例数量上限，跳过创建": "Managed instance limit reached, skipping create",
    "已达到托管实例数量上限，停止监控": "Managed instance limit reached, stopping monitor",
    "选中的自动创建 offer 已不在扫描结果中": "Selected auto-create offer is no longer in scan results",
    "已命中 offer，但没有实例创建成功": "Offers matched, but no instance was created",
    "就绪通知发送失败": "Ready notification failed",
    "监控扫描失败": "Monitor scan failed",
    "错误通知发送失败": "Error notification failed",
    "库存下降通知已跳过：Bark URL 为空": "Stock drop notification skipped; Bark URL is empty",
    "库存下降通知已发送": "Stock drop notification sent",
    "库存下降通知发送失败": "Stock drop notification failed",
    "RunPod 平台适配器尚未实现": "RunPod provider is not implemented yet",
    "必须填写 SSH 私钥路径": "ssh private key path is required",
    "必须填写 SSH 私钥路径或私钥内容": "ssh private key path or private key is required",
  };
  if (exact[text]) return exact[text];
  const patterns = [
    [/^扫描命中 (\d+) 个候选机器$/, "Scan matched {1} candidate offers"],
    [/^(.+) 库存快速下降：(\d+) -> (\d+)，减少 (\d+) 台（([\d.]+)%）$/, "{1} stock dropped quickly: {2} -> {3}, down {4} offers ({5}%)"],
    [/^offer (\d+) 创建失败$/, "Create failed for offer {1}"],
    [/^实例 (\d+) 已创建，正在检测 SSH$/, "Instance {1} created; checking connection"],
    [/^实例 (\d+) 已创建但未配置 SSH 验证；如果实例无法正常启动或无法连接，可能仍会计费，风险由用户承担$/, "Instance {1} was created without SSH verification; if it cannot start or connect, charges may still accrue and the user accepts this risk"],
    [/^实例 (\d+) SSH 检测失败，正在删除实例$/, "Connection test failed for instance {1}; deleting instance"],
    [/^实例 (\d+) 连接失败后删除失败$/, "Failed to delete instance {1} after connection failure"],
    [/^实例 (\d+) 连接失败后已删除$/, "Instance {1} deleted after connection failure"],
    [/^实例 (\d+) SSH 连接检测通过$/, "Instance {1} connection test passed"],
    [/^实例 (\d+) 就绪通知已跳过：Bark URL 为空$/, "Instance {1} ready notification skipped; Bark URL is empty"],
    [/^实例 (\d+) 就绪通知已发送$/, "Instance {1} ready notification sent"],
    [/^托管实例 (\d+) 处于 error 状态，正在删除$/, "Managed instance {1} is in error state; deleting instance"],
    [/^托管 error 实例 (\d+) 删除失败$/, "Failed to delete managed error instance {1}"],
    [/^托管 error 实例 (\d+) 已删除$/, "Managed error instance {1} deleted"],
    [/^正在验证托管实例 (\d+) 的 SSH$/, "Verifying SSH for managed instance {1}"],
    [/^托管实例 (\d+) SSH 验证失败，正在删除$/, "Managed instance {1} failed SSH verification; deleting instance"],
    [/^SSH 失败的托管实例 (\d+) 删除失败$/, "Failed to delete SSH-failed managed instance {1}"],
    [/^托管实例 (\d+) SSH 验证失败后已删除$/, "Managed instance {1} deleted after SSH verification failed"],
    [/^托管实例 (\d+) SSH 验证通过$/, "Managed instance {1} SSH verification passed"],
    [/^已请求手动删除实例 (\d+)$/, "Manual deletion requested for instance {1}"],
    [/^实例 (\d+) 手动删除失败$/, "Manual deletion failed for instance {1}"],
    [/^实例 (\d+) 手动删除完成$/, "Manual deletion completed for instance {1}"],
    [/^SSH 私钥不存在：(.+)$/, "ssh private key not found: {1}"],
    [/^实例 (\d+) SSH 检测超时：(.+)$/, "SSH check timed out for instance {1}: {2}"],
  ];
  for (const [pattern, template] of patterns) {
    const match = text.match(pattern);
    if (!match) continue;
    return template.replace(/\{(\d+)\}/g, (_, index) => match[Number(index)] || "");
  }
  return phrase(text);
}

function setBusy(value) {
  busy = value;
  Object.values(buttons).forEach((button) => {
    if (!button) return;
    button.disabled = busy;
  });
  document.querySelectorAll(".page-save-btn").forEach((button) => {
    button.disabled = busy;
  });
}

function showToast(message) {
  toast.textContent = translateMessage(message);
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    if (payload && typeof payload.error === "string" && payload.error.length > 0) {
      message = payload.error;
    }
    throw new Error(message);
  }
  return payload;
}

function migrateConfig(config) {
  if (!config || typeof config !== "object") {
    throw new Error("Invalid config payload");
  }

  const migrated = structuredClone(config);
  if (!migrated.credentials || typeof migrated.credentials !== "object") {
    throw new Error("Invalid config payload: credentials is missing");
  }
  if (!("runpod_api_key" in migrated.credentials)) {
    migrated.credentials.runpod_api_key = "";
  }

  if (!("platform" in migrated)) {
    migrated.platform = { provider: "vast" };
  } else if (!migrated.platform || typeof migrated.platform !== "object") {
    throw new Error("Invalid config payload: platform must be an object");
  } else if (!("provider" in migrated.platform)) {
    migrated.platform.provider = "vast";
  }

  if (!migrated.connection || typeof migrated.connection !== "object") {
    throw new Error("Invalid config payload: connection is missing");
  }
  if (!("ssh_private_key" in migrated.connection)) {
    migrated.connection.ssh_private_key = "";
  }

  if (!migrated.create || typeof migrated.create !== "object") {
    throw new Error("Invalid config payload: create is missing");
  }
  if (!("allow_create_without_ssh_key" in migrated.create)) {
    migrated.create.allow_create_without_ssh_key = false;
  }

  if (!("ui" in migrated)) {
    migrated.ui = { language: "zh" };
  } else if (!migrated.ui || typeof migrated.ui !== "object") {
    throw new Error("Invalid config payload: ui must be an object");
  } else if (!("language" in migrated.ui)) {
    migrated.ui.language = "zh";
  }

  if (!migrated.monitor || typeof migrated.monitor !== "object") {
    throw new Error("Invalid config payload: monitor is missing");
  }
  const monitorDefaults = {
    stock_alert_enabled: false,
    stock_alert_window_minutes: 60,
    stock_alert_min_baseline_count: 5,
    stock_alert_drop_count: 5,
    stock_alert_drop_percent: 30.0,
    stock_alert_cooldown_minutes: 60,
  };
  for (const [key, value] of Object.entries(monitorDefaults)) {
    if (!(key in migrated.monitor)) {
      migrated.monitor[key] = value;
    }
  }

  return migrated;
}

function getByPath(object, path) {
  return path.split(".").reduce((value, key) => value[key], object);
}

function setByPath(object, path, value) {
  const parts = path.split(".");
  let target = object;
  for (const key of parts.slice(0, -1)) {
    target = target[key];
  }
  target[parts[parts.length - 1]] = value;
}

function loadForm(config) {
  const migrated = migrateConfig(config);
  currentConfig = migrated;
  lastProviderValue = migrated.platform.provider;
  applyLanguage(migrated.ui.language);
  selectedGpuNames = Array.isArray(migrated.search.gpu_names) ? normalizeGpuNames(migrated.search.gpu_names) : [];
  selectedOfferIds = Array.isArray(migrated.create.target_offer_ids) ? [...migrated.create.target_offer_ids] : [];
  for (const element of form.elements) {
    if (!element.name) continue;
    const value = getByPath(migrated, element.name);
    if (element.dataset.nullableBool === "true") {
      element.value = value === null ? "" : String(value);
    } else if (element.type === "checkbox") {
      element.checked = Boolean(value);
    } else if (jsonFields.has(element.name)) {
      element.value = JSON.stringify(value, null, 2);
    } else if (value === null) {
      element.value = "";
    } else {
      element.value = value;
    }
  }
  setConfigDirty(false);
  renderGpuPicker();
  applyLanguage(currentLanguage);
}

function readForm() {
  const config = migrateConfig(currentConfig);
  for (const element of form.elements) {
    if (!element.name) continue;
    let value;
    if (element.dataset.nullableBool === "true") {
      if (element.value === "") {
        value = null;
      } else {
        value = element.value === "true";
      }
    } else if (element.type === "checkbox") {
      value = element.checked;
    } else if (jsonFields.has(element.name)) {
      value = element.value.trim() ? JSON.parse(element.value) : {};
    } else if (element.type === "number") {
      value = element.value === "" && element.dataset.nullable === "true" ? null : Number(element.value);
    } else {
      value = element.value;
    }
    setByPath(config, element.name, value);
  }
  config.search.gpu_names = [...selectedGpuNames];
  config.search.min_cuda_version = null;
  config.search.min_disk_space_gb = null;
  config.search.min_direct_ports = null;
  config.search.min_duration_days = null;
  config.search.geolocations_allow = [];
  config.search.geolocations_block = [];
  config.create.target_offer_ids = [...selectedOfferIds];
  return config;
}

async function saveConfig() {
  const config = readForm();
  currentConfig = await api("/api/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
  loadForm(currentConfig);
  setConfigDirty(false);
  await refreshState();
}

function setConfigDirty(value) {
  configDirty = value;
}

function updateClock() {
  if (!clock) return;
  clock.textContent = new Date().toLocaleTimeString();
}

async function refreshConfig() {
  const config = await api("/api/config");
  loadForm(config);
}

async function refreshGpuModels() {
  try {
    const payload = await api("/api/gpu-models-preview", {
      method: "POST",
      body: JSON.stringify(readForm()),
    });
    lastGpuPayload = payload;
    gpuModels = Array.isArray(payload.models) ? payload.models : [];
    renderGpuSource(payload);
  } catch (error) {
    lastGpuPayload = null;
    gpuSourceText.textContent = translateMessage(error.message);
    gpuModels = [];
  }
  renderGpuPicker();
}

function renderGpuSource(payload) {
  const source = payload.source === "vast" ? t("gpuSourceVast") : payload.source === "runpod" ? "RunPod" : t("gpuSourceFallback");
  gpuSourceText.textContent = t("gpuSourceCount", { count: gpuModels.length, source });
}

async function refreshInstances(forceRender = false) {
  if (!instancesList.hasChildNodes()) {
    instancesList.innerHTML = `<div class="empty">${escapeHtml(t("instancesLoading"))}</div>`;
  }
  try {
    const payload = await api("/api/instances");
    const instances = Array.isArray(payload.instances) ? payload.instances : [];
    const signature = JSON.stringify(instances);
    if (forceRender || signature !== lastInstancesSignature) {
      lastInstancesSignature = signature;
      renderAccountInstances(instances);
    }
  } catch (error) {
    instancesList.innerHTML = `<div class="empty">${escapeHtml(translateMessage(error.message))}</div>`;
  }
}

async function cleanupInstances() {
  const payload = await api("/api/instances/cleanup-errors", { method: "POST" });
  const count = Array.isArray(payload.cleaned) ? payload.cleaned.length : 0;
  showToast(t("cleanedInstances", { count }));
  await refreshState();
  await refreshInstances(true);
}

async function deleteSelectedInstances() {
  if (selectedInstanceIds.length === 0) {
    throw new Error(t("deleteNeedSelection"));
  }
  const payload = await api("/api/instances/delete", {
    method: "POST",
    body: JSON.stringify({ instance_ids: selectedInstanceIds }),
  });
  const count = Array.isArray(payload.deleted) ? payload.deleted.length : 0;
  selectedInstanceIds = [];
  showToast(t("deleteSubmitted", { count }));
  await refreshState();
  await refreshInstances(true);
}

async function clearEvents() {
  await api("/api/events/clear", { method: "POST" });
  await refreshState();
}

async function refreshTemplates(keyword = "") {
  templateList.innerHTML = `<div class="empty">${escapeHtml(t("templatesLoading"))}</div>`;
  try {
    const payload = await api(`/api/templates-preview?q=${encodeURIComponent(keyword)}`, {
      method: "POST",
      body: JSON.stringify(readForm()),
    });
    renderTemplates(Array.isArray(payload.templates) ? payload.templates : []);
    templatesLoaded = true;
  } catch (error) {
    lastTemplates = [];
    templatesLoaded = true;
    templateList.innerHTML = `<div class="empty">${escapeHtml(translateMessage(error.message))}</div>`;
  }
}

function selectedProvider() {
  const provider = form.elements["platform.provider"];
  return provider ? provider.value : "vast";
}

async function refreshTasks() {
  const payload = await api("/api/tasks");
  tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  if (selectedTaskId !== null && !tasks.some((task) => task.id === selectedTaskId)) {
    selectedTaskId = null;
  }
  renderTasks();
}

function renderGpuPicker() {
  renderSelectedGpus();
  renderGpuCategoryTabs();
  renderGpuModelList();
}

function renderSelectedGpus() {
  selectedGpuList.innerHTML = "";
  if (selectedGpuNames.length === 0) {
    selectedGpuList.innerHTML = `<span class="empty-inline">${escapeHtml(t("noGpuLimit"))}</span>`;
    return;
  }
  for (const name of selectedGpuNames) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "selected-chip";
    chip.textContent = `${name} x`;
    chip.addEventListener("click", () => toggleGpuModel(name));
    selectedGpuList.appendChild(chip);
  }
}

function renderGpuCategoryTabs() {
  gpuCategoryTabs.innerHTML = "";
  for (const category of gpuCategories) {
    const count = gpuModels.filter((model) => category.match(model.name)).length;
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "gpu-category";
    if (activeGpuCategory === category.id) tab.classList.add("active");
    tab.innerHTML = `<span>${escapeHtml(phrase(category.label))}</span><strong>${count}</strong>`;
    tab.addEventListener("click", () => {
      activeGpuCategory = category.id;
      renderGpuPicker();
    });
    gpuCategoryTabs.appendChild(tab);
  }
}

function renderGpuModelList() {
  const keyword = gpuSearchInput.value.trim().toLowerCase();
  const category = gpuCategories.find((item) => item.id === activeGpuCategory);
  let filtered = gpuModels.filter((model) => category.match(model.name));
  if (keyword) {
    filtered = gpuModels.filter((model) => model.name.toLowerCase().includes(keyword));
  }
  filtered = filtered.sort((a, b) => modelRank(b.name) - modelRank(a.name) || a.name.localeCompare(b.name)).slice(0, 120);

  gpuModelList.innerHTML = "";
  if (filtered.length === 0) {
    gpuModelList.innerHTML = `<div class="empty">${escapeHtml(t("noGpuMatches"))}</div>`;
    return;
  }

  for (const model of filtered) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "gpu-card";
    if (selectedGpuNames.includes(model.name)) option.classList.add("active");
    const count = typeof model.count === "number" ? t("offerCount", { count: model.count }) : t("selectable");
    option.innerHTML = `
      <span class="gpu-card-title">${escapeHtml(model.name)}</span>
      <span class="gpu-card-meta">${escapeHtml(gpuFamily(model.name))} · ${escapeHtml(count)}</span>
    `;
    option.addEventListener("click", () => toggleGpuModel(model.name));
    gpuModelList.appendChild(option);
  }
}

function normalizeGpuNames(names) {
  const normalized = [];
  for (const rawName of names) {
    if (typeof rawName !== "string") continue;
    const items = splitGpuName(rawName);
    for (const item of items) {
      if (!normalized.includes(item)) normalized.push(item);
    }
  }
  return normalized;
}

function splitGpuName(name) {
  const chunks = name
    .split(/[,，;；|\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const result = [];
  for (const chunk of chunks) {
    const parts = chunk.split(/\s+/);
    if (parts.length >= 4 && parts.length % 2 === 0) {
      const adjacentRtx = [];
      for (let index = 0; index < parts.length; index += 2) {
        if (parts[index].toUpperCase() !== "RTX") {
          adjacentRtx.length = 0;
          break;
        }
        adjacentRtx.push(`RTX ${parts[index + 1]}`);
      }
      if (adjacentRtx.length > 0) {
        result.push(...adjacentRtx);
        continue;
      }
    }
    result.push(parts.join(" "));
  }
  return result;
}

function modelRank(name) {
  if (/^(B200|B300|H200|H100|A100|A800)/.test(name)) return 50;
  if (/^(RTX 5090|RTX 5080|RTX 4090|RTX 4080|RTX 3090)/.test(name)) return 40;
  if (/^(L40S|L40|L4)/.test(name)) return 30;
  if (/RTX PRO|RTX A/.test(name)) return 20;
  return 0;
}

function gpuFamily(name) {
  if (/^(B200|B300|H200|H100|A100|A800|L40S|L40|L4)/.test(name)) return t("familyDatacenter");
  if (/^RTX 5/.test(name)) return "RTX 50";
  if (/^RTX 4/.test(name)) return "RTX 40";
  if (/^RTX 30|^RTX 31|^RTX 32/.test(name)) return "RTX 30";
  if (/RTX PRO|RTX A|Quadro|Q RTX/.test(name)) return t("familyWorkstation");
  if (/GTX|Tesla|P100|P40|P4|T4|V100/.test(name)) return t("familyLegacy");
  return t("familyOther");
}

function toggleGpuModel(name) {
  if (selectedGpuNames.includes(name)) {
    selectedGpuNames = selectedGpuNames.filter((item) => item !== name);
  } else {
    selectedGpuNames = [...selectedGpuNames, name];
  }
  renderGpuPicker();
}

function setupTabs() {
  const tabs = [...document.querySelectorAll("[data-tab-target]")];
  const panels = [...document.querySelectorAll("[data-tab-panel]")];
  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tabTarget;
      activeTab = target;
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.tabPanel === target));
      if (target === "instances") refreshInstances(true);
      if (target === "activity") refreshTasks().catch((error) => showToast(error.message));
      if (target === "scan" && !templatesLoaded) refreshTemplates();
    });
  }
}

async function refreshState() {
  const state = await api("/api/state");
  renderState(state);
}

function renderState(state) {
  lastState = state;
  const recentOffers = Array.isArray(state.recent_offers) ? state.recent_offers : [];
  currentStateOffers = recentOffers;
  runBadge.textContent = state.running ? t("monitorRunning") : t("notRunning");
  runBadge.classList.toggle("muted", !state.running);
  scanBadge.textContent = state.scan_in_progress ? t("scanning") : t("idle");
  scanBadge.classList.toggle("muted", !state.scan_in_progress);
  lastScanText.textContent = state.last_scan_at ? t("lastScan", { time: formatDate(state.last_scan_at) }) : t("notScanned");
  renderOfferGpuFilters(recentOffers);
  renderOffers(recentOffers);
  renderSelectedOfferText(recentOffers);
  const events = Array.isArray(state.events) ? state.events : [];
  renderSideEvents(events, state);
  renderActiveTaskFromState(state);
}

function renderOffers(offers) {
  offersList.innerHTML = "";
  if (!offers.length) {
    offersList.innerHTML = `<div class="empty">${escapeHtml(t("noOffers"))}</div>`;
    return;
  }
  const rankedOffers = offers.map((offer, index) => ({ offer, rank: index + 1 }));
  const filteredOffers = filterOffersByGpuCount(rankedOffers);
  if (!filteredOffers.length) {
    offersList.innerHTML = `<div class="empty">${escapeHtml(t("noOffersForGpuCount"))}</div>`;
    return;
  }

  for (const itemData of filteredOffers.slice(0, maxVisibleOffers)) {
    const offer = itemData.offer;
    const selected = selectedOfferIds.includes(offer.id);
    const item = document.createElement("article");
    item.className = "offer";
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");
    item.setAttribute("aria-pressed", selected ? "true" : "false");
    item.setAttribute(
      "aria-label",
      t("selectOfferAria", { rank: itemData.rank, gpus: offer.num_gpus, gpuName: offer.gpu_name, offerId: offer.id }),
    );
    if (selected) item.classList.add("selected");
    item.innerHTML = `
      <div class="offer-head">
        <div class="offer-title-group">
          <span class="offer-rank">Rank ${escapeHtml(itemData.rank)}</span>
          <h3>${escapeHtml(offer.num_gpus)}x ${escapeHtml(offer.gpu_name)}</h3>
        </div>
      </div>
      <div class="offer-id">Offer #${escapeHtml(offer.id)}</div>
      <div class="metrics">
        ${metric(t("hourlyPrice"), money(offer.dph_total))}
        ${metric("TFLOPS/USD", number(offer.flops_per_usd, 2))}
        ${metric(t("totalTflops"), number(offer.total_flops, 2))}
        ${metric(t("reliability"), offer.reliability === null ? "-" : number(offer.reliability, 3))}
        ${metric(t("gpuRam"), offer.gpu_ram_gb === null ? "-" : number(offer.gpu_ram_gb, 1))}
        ${metric(t("region"), offer.geolocation === "" ? "-" : offer.geolocation)}
      </div>
    `;
    item.addEventListener("click", () => toggleOfferSelection(offer.id));
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggleOfferSelection(offer.id);
    });
    offersList.appendChild(item);
  }
}

function renderOfferGpuFilters(offers) {
  offerGpuFilters.innerHTML = "";
  const counts = offerGpuCounts(offers);
  if (!counts.length) return;

  const values = counts.map((count) => String(count));
  if (activeOfferGpuCountFilter === null || (activeOfferGpuCountFilter !== "all" && !values.includes(activeOfferGpuCountFilter))) {
    activeOfferGpuCountFilter = String(offers[0].num_gpus);
  }

  const filters = [{ value: "all", label: t("all"), count: offers.length }];
  for (const gpuCount of counts) {
    const matched = offers.filter((offer) => offer.num_gpus === gpuCount).length;
    filters.push({ value: String(gpuCount), label: t("gpuCards", { count: gpuCount }), count: matched });
  }

  for (const filter of filters) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "offer-filter";
    if (activeOfferGpuCountFilter === filter.value) button.classList.add("active");
    button.innerHTML = `<span>${escapeHtml(filter.label)}</span><strong>${escapeHtml(filter.count)}</strong>`;
    button.addEventListener("click", () => {
      activeOfferGpuCountFilter = filter.value;
      renderOfferGpuFilters(currentStateOffers);
      renderOffers(currentStateOffers);
    });
    offerGpuFilters.appendChild(button);
  }
}

function offerGpuCounts(offers) {
  const counts = [];
  for (const offer of offers) {
    if (!Number.isInteger(offer.num_gpus) || offer.num_gpus < 1) continue;
    if (!counts.includes(offer.num_gpus)) counts.push(offer.num_gpus);
  }
  return counts.sort((left, right) => left - right);
}

function filterOffersByGpuCount(rankedOffers) {
  if (activeOfferGpuCountFilter === "all") return rankedOffers;
  return rankedOffers.filter((item) => String(item.offer.num_gpus) === activeOfferGpuCountFilter);
}

function toggleOfferSelection(offerId) {
  if (selectedOfferIds.includes(offerId)) {
    selectedOfferIds = selectedOfferIds.filter((item) => item !== offerId);
  } else {
    selectedOfferIds = [offerId];
  }
  renderOffers(lastRenderedOffers());
  renderSelectedOfferText(lastRenderedOffers());
  saveOfferTargets().catch((error) => showToast(error.message));
}

function lastRenderedOffers() {
  return currentStateOffers;
}

async function saveOfferTargets() {
  const payload = await api("/api/create-targets", {
    method: "POST",
    body: JSON.stringify({ target_offer_ids: selectedOfferIds }),
  });
  selectedOfferIds = [...payload.target_offer_ids];
  renderOffers(lastRenderedOffers());
  renderSelectedOfferText(lastRenderedOffers());
}

function renderSelectedOfferText(offers) {
  if (!selectedOfferText) return;
  if (selectedOfferIds.length === 0) {
    selectedOfferText.textContent = t("selectedOfferDefault");
    return;
  }
  const selected = offers.find((offer) => selectedOfferIds.includes(offer.id));
  if (selected) {
    selectedOfferText.textContent = t("selectedOffer", {
      gpus: selected.num_gpus,
      gpuName: selected.gpu_name,
      offerId: selected.id,
    });
  } else {
    selectedOfferText.textContent = t("selectedOfferMissing", { offerId: selectedOfferIds[0] });
  }
}

function createdStatusLabel(check, cleanup) {
  if (cleanup.status === "deleted") return t("deleted");
  if (cleanup.status === "delete_failed") return t("deleteFailed");
  if (cleanup.status === "deleting") return t("deleting");
  if (cleanup.status === "checking") return t("sshChecking");
  if (cleanup.status === "kept_unverified") return t("unverifiedKept");
  if (check.ok) return t("connectionPassed");
  return t("connectionChecking");
}

function createdStatusClass(check, cleanup) {
  if (cleanup.status === "deleted") return "warn";
  if (cleanup.status === "delete_failed") return "bad";
  if (cleanup.status === "deleting") return "pending";
  if (cleanup.status === "checking") return "pending";
  if (cleanup.status === "kept_unverified") return "pending";
  return check.ok ? "ok" : "pending";
}

function cleanupLabel(status) {
  const labels = {
    kept: t("kept"),
    kept_unverified: t("unverifiedKept"),
    checking: t("checking"),
    deleting: t("deleting"),
    deleted: t("deleted"),
    delete_failed: t("deleteFailed"),
  };
  return labels[status] || status;
}

function levelLabel(level) {
  if (level === "success") return t("eventSuccess");
  if (level === "warn") return t("eventWarn");
  if (level === "error") return t("eventError");
  return t("eventInfo");
}

function renderSideEvents(events, state) {
  if (!sideEventList || !sideRunText) return;
  sideRunText.textContent = state.running ? t("sideRunning") : t("sideStopped");
  sideEventList.innerHTML = "";
  if (!events.length) {
    sideEventList.innerHTML = `<div class="empty">${escapeHtml(t("noSideLogs"))}</div>`;
    return;
  }
  for (const event of events.slice(0, 18)) {
    const item = document.createElement("div");
    item.className = `side-event ${event.level}`;
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(translateMessage(event.message))}</strong>
        <span>${escapeHtml(formatDate(event.ts))} · ${escapeHtml(levelLabel(event.level))}</span>
      </div>
    `;
    sideEventList.appendChild(item);
  }
}

function renderAccountInstances(instances) {
  lastInstances = instances;
  instancesList.innerHTML = "";
  if (!instances.length) {
    instancesList.innerHTML = `<div class="empty">${escapeHtml(t("noAccountInstances"))}</div>`;
    return;
  }
  const currentIds = instances.map(instanceIdFromRow).filter((id) => id !== null);
  selectedInstanceIds = selectedInstanceIds.filter((id) => currentIds.includes(id));
  for (const instance of instances) {
    const instanceId = instanceIdFromRow(instance);
    const gpuName = instance.gpu_name || instance.gpu_name_str || instance.gpu_display_name || "-";
    const numGpus = instance.num_gpus || instance.gpu_count || "-";
    const hasError = instanceHasError(instance);
    const status = instanceStatusText(instance);
    const label = instance.label || instance.name || "-";
    const ssh = instance.ssh_host && instance.ssh_port ? `${instance.ssh_host}:${instance.ssh_port}` : "-";
    const item = document.createElement("article");
    item.className = "instance-item";
    const selected = instanceId !== null && selectedInstanceIds.includes(instanceId);
    if (selected) item.classList.add("selected");
    item.innerHTML = `
      <div class="created-head">
        <label class="instance-select">
          <input type="checkbox" ${selected ? "checked" : ""} ${instanceId === null ? "disabled" : ""} />
          <span>${escapeHtml(t("choose"))}</span>
        </label>
        <div>
          <strong>#${escapeHtml(instanceId === null ? "-" : instanceId)}</strong>
          <span>${escapeHtml(numGpus)}x ${escapeHtml(gpuName)}</span>
        </div>
        <span class="status-pill ${hasError ? "bad" : ""}">${escapeHtml(status)}</span>
      </div>
      <div class="metrics">
        ${metric(t("label"), label)}
        ${metric(t("price"), instance.dph_total === undefined ? "-" : money(instance.dph_total))}
        ${metric("SSH", ssh)}
        ${metric(t("region"), instance.geolocation || "-")}
        ${metric(t("statusDetail"), instance.status_msg || "-")}
      </div>
    `;
    const checkbox = item.querySelector('input[type="checkbox"]');
    checkbox.addEventListener("change", () => {
      if (instanceId === null) return;
      if (checkbox.checked) {
        selectedInstanceIds = [...selectedInstanceIds, instanceId];
      } else {
        selectedInstanceIds = selectedInstanceIds.filter((id) => id !== instanceId);
      }
      renderAccountInstances(instances);
    });
    instancesList.appendChild(item);
  }
}

function renderTasks() {
  if (!taskList) return;
  taskList.innerHTML = "";
  if (!tasks.length) {
    taskList.innerHTML = `<div class="empty">${escapeHtml(t("noTasks"))}</div>`;
    renderActiveTaskFromState(lastState || {});
    return;
  }
  if (selectedTaskId === null) selectedTaskId = tasks[0].id;
  for (const task of tasks) {
    const config = task.config || {};
    const item = document.createElement("article");
    item.className = "task-item";
    if (task.id === selectedTaskId) item.classList.add("selected");
    if (task.active || task.status === "running") item.classList.add("active");
    item.innerHTML = `
      <div class="task-head">
        <div>
          <strong>${escapeHtml(task.name)}</strong>
          <span>${escapeHtml(task.id)}</span>
        </div>
        <span class="status-pill ${task.status === "running" ? "ok" : task.status === "error" ? "bad" : ""}">${escapeHtml(task.status || "-")}</span>
      </div>
      <div class="metrics">
        ${taskMetric(t("taskPlatform"), config.platform ? config.platform.provider : "-")}
        ${taskMetric(t("taskGpu"), summarizeGpuNames(config))}
        ${taskMetric(t("taskPrice"), summarizePrice(config))}
        ${taskMetric(t("taskCreateLimit"), summarizeCreateLimit(config))}
        ${taskMetric(t("taskInterval"), summarizeScanInterval(config))}
        ${taskMetric(t("taskStockAlert"), summarizeStockAlert(config))}
        ${taskMetric(t("taskUpdatedAt"), formatMaybeDate(task.updated_at))}
      </div>
    `;
    item.addEventListener("click", () => selectTask(task.id));
    taskList.appendChild(item);
  }
  renderActiveTaskFromState(lastState || {});
}

function renderActiveTaskFromState(state) {
  if (!activeTaskPanel) return;
  const activeTask = state.active_task_id ? taskFromState(state) : tasks.find((task) => task.active || task.status === "running");
  if (!activeTask) {
    activeTaskPanel.innerHTML = `<div class="empty">${escapeHtml(t("noActiveTask"))}</div>`;
    return;
  }
  const config = activeTask.config || {};
  activeTaskPanel.innerHTML = `
    <div class="task-summary-title">
      <strong>${escapeHtml(t("activeTask"))}: ${escapeHtml(activeTask.name || activeTask.id)}</strong>
      <span class="status-pill ok">${escapeHtml(activeTask.status || "running")}</span>
    </div>
    <div class="metrics">
      ${taskMetric(t("taskPlatform"), config.platform ? config.platform.provider : "-")}
      ${taskMetric(t("taskGpu"), summarizeGpuNames(config))}
      ${taskMetric(t("taskPrice"), summarizePrice(config))}
      ${taskMetric(t("taskAutoCreate"), config.create && config.create.auto_create_enabled ? t("enabled") : t("disabled"))}
      ${taskMetric(t("taskStockAlert"), summarizeStockAlert(config))}
      ${taskMetric(t("taskLastScan"), formatMaybeDate(activeTask.last_scan_at))}
      ${taskMetric(t("taskNextScan"), formatMaybeDate(activeTask.next_scan_at))}
    </div>
  `;
}

function taskFromState(state) {
  return {
    id: state.active_task_id,
    name: state.active_task_name || state.active_task_id,
    config: state.active_task_config || {},
    status: state.running ? "running" : "stopped",
    last_scan_at: state.last_scan_at,
    next_scan_at: state.next_scan_at,
    cycles: state.cycles,
    last_error: state.last_error,
  };
}

function selectTask(taskId) {
  selectedTaskId = taskId;
  const task = selectedTask();
  if (taskNameInput && task) taskNameInput.value = task.name;
  if (task && task.config) loadForm(task.config);
  renderTasks();
}

function selectedTask() {
  return tasks.find((task) => task.id === selectedTaskId) || null;
}

function currentTaskBody() {
  const name = taskNameInput ? taskNameInput.value.trim() : "";
  if (!name) throw new Error(t("taskNameRequired"));
  return { name, config: readForm() };
}

async function createTask() {
  const payload = await api("/api/tasks", {
    method: "POST",
    body: JSON.stringify(currentTaskBody()),
  });
  selectedTaskId = payload.task.id;
  await refreshTasks();
}

async function updateTask() {
  const task = selectedTask();
  if (!task) throw new Error(t("selectTaskFirst"));
  await api(`/api/tasks/${encodeURIComponent(task.id)}`, {
    method: "PUT",
    body: JSON.stringify(currentTaskBody()),
  });
  await refreshTasks();
}

async function startSelectedTask() {
  const task = selectedTask();
  if (!task) throw new Error(t("selectTaskFirst"));
  await api(`/api/tasks/${encodeURIComponent(task.id)}/start`, { method: "POST" });
  await refreshState();
  await refreshTasks();
}

async function stopSelectedTask() {
  await api("/api/monitor/stop", { method: "POST" });
  await refreshState();
  await refreshTasks();
}

async function deleteSelectedTask() {
  const task = selectedTask();
  if (!task) throw new Error(t("selectTaskFirst"));
  await api(`/api/tasks/${encodeURIComponent(task.id)}`, { method: "DELETE" });
  selectedTaskId = null;
  await refreshTasks();
}

function taskMetric(label, value) {
  return metric(label, value === undefined || value === null || value === "" ? "-" : value);
}

function summarizeGpuNames(config) {
  const names = config.search && Array.isArray(config.search.gpu_names) ? config.search.gpu_names : [];
  if (!names.length) return t("all");
  return names.slice(0, 3).join(", ");
}

function summarizePrice(config) {
  const price = config.search ? config.search.max_price_per_hour : null;
  return price === null || price === undefined ? "-" : money(price);
}

function summarizeCreateLimit(config) {
  if (!config.create) return "-";
  return `${config.create.max_created_instances}/${config.create.max_creates_per_cycle}`;
}

function summarizeScanInterval(config) {
  if (!config.monitor) return "-";
  return `${config.monitor.scan_interval_seconds}s`;
}

function summarizeStockAlert(config) {
  if (!config.monitor || !config.monitor.stock_alert_enabled) return t("disabled");
  return `${config.monitor.stock_alert_drop_count}/${number(config.monitor.stock_alert_drop_percent, 1)}%`;
}

function formatMaybeDate(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return "-";
  return formatDate(seconds);
}

function renderTemplates(templates) {
  lastTemplates = templates;
  templateList.innerHTML = "";
  if (!templates.length) {
    templateList.innerHTML = `<div class="empty">${escapeHtml(t("noTemplates"))}</div>`;
    return;
  }
  for (const template of templates.slice(0, 24)) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "template-card";
    const name = template.name || template.title || t("unnamedTemplate");
    const image = template.image || "-";
    const hash = template.hash_id || "";
    item.innerHTML = `
      <span class="template-title">${escapeHtml(name)}</span>
      <span class="template-image">${escapeHtml(image)}</span>
      <span class="template-meta">${template.recommended ? t("recommended") : t("template")} · ${escapeHtml(t("createdTimes", { count: template.count_created || 0 }))}</span>
    `;
    item.addEventListener("click", () => selectTemplate(template));
    templateList.appendChild(item);
  }
}

function selectTemplate(template) {
  const hashInput = form.elements["create.template_hash"];
  const imageInput = form.elements["create.image"];
  const runtypeInput = form.elements["create.runtype"];
  const onstartInput = form.elements["create.onstart_cmd"];
  const argsInput = form.elements["create.args"];
  const dockerExtraInput = form.elements["create.docker_extra"];

  hashInput.value = template.hash_id || "";
  if (template.image) imageInput.value = template.image;
  if (template.runtype) runtypeInput.value = template.runtype;
  if (template.onstart) onstartInput.value = template.onstart;
  if (template.args) argsInput.value = template.args;
  if (template.docker_extra) dockerExtraInput.value = template.docker_extra;
  showToast(t("templateSelected", { name: template.name || template.hash_id || "template" }));
}

function instanceHasError(instance) {
  const values = [instance.actual_status, instance.cur_state, instance.next_state, instance.intended_status, instance.status];
  if (values.some((value) => typeof value === "string" && ["error", "failed"].includes(value.toLowerCase()))) {
    return true;
  }
  if (instanceHasConflictingLoadingState(instance)) return true;
  return typeof instance.status_msg === "string" && instance.status_msg.toLowerCase().includes("error");
}

function instanceStatusText(instance) {
  if (instanceHasError(instance)) {
    if (typeof instance.status_msg === "string" && instance.status_msg.trim()) {
      return t("statusErrorPrefix", { message: instance.status_msg.trim() });
    }
    if (instanceHasConflictingLoadingState(instance)) return t("statusConflict");
    return t("statusError");
  }
  return instance.actual_status || instance.cur_state || instance.status || "-";
}

function instanceHasConflictingLoadingState(instance) {
  if (typeof instance.actual_status !== "string" || instance.actual_status.toLowerCase() !== "loading") return false;
  const values = [instance.cur_state, instance.next_state, instance.intended_status];
  return values.some((value) => typeof value === "string" && value.toLowerCase() === "stopped");
}

function instanceIdFromRow(instance) {
  const value = instance.id || instance.instance_id;
  if (Number.isInteger(value)) return value;
  if (typeof value === "string" && value.trim()) return value.trim();
  return null;
}

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function money(value) {
  return `$${number(value, 3)}`;
}

function number(value, digits) {
  return Number(value).toFixed(digits);
}

function formatDate(seconds) {
  const locale = currentLanguage === "en" ? "en-US" : "zh-CN";
  return new Date(seconds * 1000).toLocaleString(locale);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function runAction(label, callback) {
  setBusy(true);
  try {
    await callback();
    showToast(label);
    await refreshState();
  } catch (error) {
    showToast(error.message);
    throw error;
  } finally {
    setBusy(false);
  }
}

document.querySelectorAll(".page-save-btn").forEach((button) => {
  button.addEventListener("click", () => runAction(t("configSaved"), saveConfig));
});
buttons.refreshTasks.addEventListener("click", () => runAction(t("tasksRefreshed"), refreshTasks));
buttons.createTask.addEventListener("click", () => runAction(t("taskCreated"), createTask));
buttons.updateTask.addEventListener("click", () => runAction(t("taskUpdated"), updateTask));
buttons.startTask.addEventListener("click", () => runAction(t("taskStarted"), startSelectedTask));
buttons.stopTask.addEventListener("click", () => runAction(t("taskStopped"), stopSelectedTask));
buttons.deleteTask.addEventListener("click", () => runAction(t("taskDeleted"), deleteSelectedTask));
buttons.scan.addEventListener("click", () => runAction(t("scanDone"), async () => {
  await saveConfig();
  await api("/api/scan", { method: "POST" });
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}));
buttons.start.addEventListener("click", () => runAction(t("monitorStarted"), async () => {
  await saveConfig();
  await api("/api/monitor/start", { method: "POST" });
}));
buttons.stop.addEventListener("click", () => runAction(t("monitorStopped"), async () => {
  await api("/api/monitor/stop", { method: "POST" });
}));
buttons.bark.addEventListener("click", () => runAction(t("barkSent"), async () => {
  await saveConfig();
  await api("/api/test/bark", { method: "POST" });
}));
buttons.refreshInstances.addEventListener("click", () => runAction(t("instancesRefreshed"), () => refreshInstances(true)));
buttons.cleanupInstances.addEventListener("click", () => runAction(t("errorInstancesCleaned"), cleanupInstances));
buttons.deleteInstances.addEventListener("click", () => runAction(t("selectedInstancesDeleted"), deleteSelectedInstances));
buttons.clearEvents.addEventListener("click", () => runAction(t("eventsCleared"), clearEvents));
buttons.templateSearch.addEventListener("click", () => refreshTemplates(templateSearchInput.value.trim()));
buttons.templatePopular.addEventListener("click", () => {
  templateSearchInput.value = "";
  refreshTemplates();
});

gpuSearchInput.addEventListener("input", renderGpuPicker);

form.addEventListener("input", () => {
  setConfigDirty(true);
  const provider = form.elements["platform.provider"];
  if (provider && provider === document.activeElement) {
    const nextProvider = provider.value;
    if (lastProviderValue && nextProvider !== lastProviderValue) {
      selectedOfferIds = [];
      const hashInput = form.elements["create.template_hash"];
      if (hashInput) hashInput.value = "";
      lastProviderValue = nextProvider;
    }
    gpuModels = [];
    lastTemplates = [];
    templatesLoaded = false;
    renderGpuPicker();
    templateList.innerHTML = "";
    refreshGpuModels().catch((error) => showToast(error.message));
    refreshTemplates().catch((error) => showToast(error.message));
  }
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => showToast(t("configDirty")), 350);
});

if (languageSelect) {
  languageSelect.addEventListener("change", () => {
    applyLanguage(languageSelect.value);
    if (lastGpuPayload) renderGpuSource(lastGpuPayload);
    renderGpuPicker();
    if (lastState) renderState(lastState);
    if (templatesLoaded) renderTemplates(lastTemplates);
    if (lastInstances.length || activeTab === "instances") renderAccountInstances(lastInstances);
    renderTasks();
    setConfigDirty(true);
  });
}

setupTabs();
updateClock();
refreshConfig()
  .then(() => Promise.all([refreshGpuModels(), refreshState(), refreshTemplates(), refreshTasks()]))
  .catch((error) => showToast(error.message));

window.setInterval(() => {
  updateClock();
  if (!busy) {
    refreshState().catch((error) => showToast(error.message));
    if (activeTab === "instances") refreshInstances(false).catch((error) => showToast(error.message));
    if (activeTab === "activity") refreshTasks().catch((error) => showToast(error.message));
  }
}, 5000);
