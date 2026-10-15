/* Standalone design prototype. All sessions, actions, and artifacts are fixtures. */
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  bot: '<rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 3v4M9 13h.01M15 13h.01M9 17h6M1 12v4M23 12v4"/>',
  spark: '<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z"/>',
  chart: '<path d="M4 3v18h17M8 16v-4M13 16V7M18 16v-7"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>',
  right: '<path d="m9 6 6 6-6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  settings: '<path d="m9 3-1 3-3 1-2 4 2 2v4l4 3 3-1 3 1 4-3v-4l2-2-2-4-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  plug: '<path d="m7 3 4 4m6-4-4 4M5 9h14v3a7 7 0 0 1-14 0V9Zm7 10v3"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  computer: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>',
  expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  browser: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 8h18M7 5.5h.01M10 5.5h.01"/>',
  terminal: '<path d="m5 7 5 5-5 5m8 0h6"/>',
  folder: '<path d="M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
  activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  back: '<path d="M20 12H5m6-6-6 6 6 6"/>',
  attach: '<path d="m8 13 7-7a3 3 0 0 1 4 4L9 20a5 5 0 0 1-7-7L13 2"/>',
  file: '<path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-7-7Z"/><path d="M13 2v7h7M8 13h8m-8 4h6"/>',
  mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8"/>',
  up: '<path d="M12 20V4m-6 6 6-6 6 6"/>',
  record: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2"/>',
  cursor: '<path d="m4 2 15 12-7 1-4 6L4 2Z"/>',
  refresh: '<path d="M20 7a9 9 0 1 0 1 8M20 2v6h-6"/>',
  share: '<path d="M12 15V2m-5 5 5-5 5 5M5 12H3v9h18v-9h-2"/>',
  split: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 14h18"/>',
  columns: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/>',
  cloud: '<path d="M6 18a5 5 0 1 1 0-10 7 7 0 0 1 13 1 4.5 4.5 0 0 1-1 9H6Z"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
};
const icon = (name, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.spark}</svg>`;
const avatar = (type = 'bot', color = '') => `<span class="avatar ${color}">${icon(type)}</span>`;
const iconButton = (name, label, action) => `<button class="icon-button" title="${label}" aria-label="${label}" ${action ? `data-action="${action}"` : `data-toast="${label} is a concept control in this mockup."`}>${icon(name)}</button>`;
const view = new URLSearchParams(location.search).get('view') || 'workspace';
const isFiles = view === 'files';
const isExpanded = view === 'computer' || isFiles;
const state = { approved: false, control: false };

function header() {
  return `<header class="global">
    <a class="brand" href="?view=workspace" aria-label="Agent Control home"><svg class="brand-mark" viewBox="0 0 30 30" aria-hidden="true"><path d="m4 24 10-19h5L9 24H4Zm9 0 6-12 7 12h-6l-3-5" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>Agent Control</a>
    <span class="divider"></span><button class="workspace-switch row" data-toast="Data Operations is the sample workspace.">${icon('grid')}Data Operations ${icon('chevron')}</button>
    <label class="search row">${icon('search')}<input id="search" aria-label="Search bots" placeholder="Search bots, conversations, files…"><kbd>Ctrl K</kbd></label>
    <span class="spacer"></span><a class="button new-bot" href="?view=workspace" data-toast="New Bot is a concept control in this mockup.">${icon('plus')} New Bot</a>
    ${iconButton('bell', 'Notifications', 'notifications')}<span class="divider"></span><button class="avatar person" title="Duy Tran" data-toast="Duy Tran · Data Operations">DT</button>
  </header>`;
}

function rail() {
  if (isExpanded) return `<aside class="rail slim-rail" aria-label="Workspace navigation">
    <a class="icon-button" href="?view=workspace" title="Back to workspace">${icon('grid')}</a><span class="rail-divider"></span>
    <a class="avatar selected" href="?view=workspace" title="Orders ETL">${icon('bot')}</a><button class="avatar violet" data-toast="Reporting Bot is preparing the daily summary." title="Reporting Bot">${icon('chart')}</button>
    <button class="avatar green" data-toast="Research Bot has completed its task." title="Research Bot">${icon('spark')}</button><button class="avatar amber" data-toast="Dev Assistant is idle." title="Dev Assistant">${icon('code')}</button>
    <span class="spacer"></span>${iconButton('clock', 'Routines')}${iconButton('plug', 'Connect library')}${iconButton('settings', 'Settings')}</aside>`;
  const bots = [
    ['Orders ETL', 'bot', '', 'amber', 'Waiting for approval', 'Ready to publish curated orders', 'now'],
    ['Reporting Bot', 'chart', 'violet', 'cyan', 'Thinking', 'Preparing the daily summary', '1m'],
    ['Research Bot', 'spark', 'green', 'green', 'Idle', 'Market brief is ready', '12m'],
    ['Dev Assistant', 'code', 'amber', 'muted', 'Idle', 'All checks passed', '28m'],
  ];
  return `<aside class="rail" aria-label="Workspace navigation">
    <div class="rail-top row between"><span class="eyebrow">Workspace</span>${iconButton('panel', 'Collapse sidebar', 'collapse')}</div>
    <button class="nav-item" data-toast="Overview shows all four bots in the Data Operations workspace.">${icon('grid')}Overview <span class="count">4</span></button>
    <div class="rail-section row between"><span class="eyebrow">Your bots <span class="quiet"> / 4</span></span>${iconButton('plus', 'Add bot')}</div>
    <div class="bots">${bots.map((b, i) => `<button class="bot ${i === 0 ? 'active' : ''}" data-bot="${b[0]}" ${i ? `data-toast="${b[0]}: ${b[5]}."` : 'data-action="orders"'}>${avatar(b[1], b[2])}<span class="bot-detail"><span class="row"><span class="bot-name">${b[0]}</span><time class="bot-time">${b[6]}</time></span><span class="bot-status ${b[3]}"><i class="dot"></i><span ${i === 0 ? 'id="bot-status"' : ''}>${b[4]}</span></span><span class="bot-preview">${b[5]}</span></span></button>`).join('')}</div>
    <div class="rail-section row between"><span class="eyebrow">Groups</span>${iconButton('plus', 'Create group')}</div>
    <button class="nav-item group" data-toast="Data Pipeline groups Orders ETL and Reporting Bot."><span class="stack-avatars"><span>E</span><span>R</span></span>Data Pipeline<span class="count">2</span></button>
    <button class="nav-item group" data-toast="Dev Assist is a sample group.">${icon('code')}Dev Assist</button>
    <div class="rail-bottom"><button class="nav-item" data-toast="Create recurring tasks from the conversation.">${icon('clock')}Routines<span class="count">3</span></button><button class="nav-item" data-toast="Connect your tools and services.">${icon('plug')}Marketplace</button><button class="nav-item" data-toast="Manage bots, credentials, and approval rules.">${icon('settings')}Settings</button>
    <div class="usage"><div class="row between"><span style="font-size:10px">Cloud sessions</span><span class="pill green"><i class="dot"></i>2 active</span></div><div class="usage-track"></div><p>Your workspace stays with your bots.</p></div>
    <div class="rail-foot row">${icon('shield')}Private workspace<span class="spacer"></span>${icon('chevron')}</div></div>
  </aside>`;
}

function tabs(active, large = false) {
  return `<nav class="panel-tabs" aria-label="Cloud computer views">${[['Browser','browser','computer'],['Terminal','terminal','computer&tab=terminal'],['Filesystem','folder','files'],['Activity','activity','files&tab=activity']].map(([label, glyph, target]) => `<a class="panel-tab ${label === active ? 'active' : ''}" ${label === active ? 'aria-current="page"' : ''} href="?view=${target}">${large || label !== 'Filesystem' ? icon(glyph) : ''}${label}</a>`).join('')}</nav>`;
}

function miniBrowser() {
  return `<div class="live-browser"><div class="browser-chrome">${icon('back')}${icon('refresh')}<div class="browser-url">${icon('lock')}<span>file:///workspace/preview.html</span></div>${icon('more')}</div>
    <div class="mini-report"><div class="report-brand">${icon('chart')}ORDERS / DAILY PIPELINE</div><h3>Daily orders</h3><p>October 6, 2026 · Validation preview</p>
    <div class="mini-metrics"><div class="mini-metric"><span>Source rows</span><strong>3</strong></div><div class="mini-metric"><span>Paid orders</span><strong>2</strong></div><div class="mini-metric"><span>Total value</span><strong>$15.75</strong></div></div>
    <table class="mini-table"><thead><tr><th>ORDER ID</th><th>CUSTOMER</th><th>AMOUNT</th><th>STATUS</th></tr></thead><tbody><tr><td>1001</td><td>c-9</td><td>$12.50</td><td>Paid</td></tr><tr><td>1003</td><td>c-9</td><td>$3.25</td><td>Paid</td></tr></tbody></table></div>
    <div class="browser-status">${icon('eye')}Latest frame · Ready for your review<span class="spacer"></span><i class="dot cyan"></i></div></div>`;
}

function approval() {
  return `<div class="approval" id="approval"><div class="approval-content"><div class="row amber">${icon('shield')}<h3>Approval required</h3><span class="spacer"></span><span class="pill amber">Cloud write</span></div><p>Run the pipeline and publish the cleaned CSV and summary to <span style="color:#e7d4b0">etlstore / curated</span>.</p><div class="command">${icon('terminal')}python3 /workspace/etl_orders.py</div><div class="approval-details row">${icon('lock')}Credentials stay in the sandbox · 30s command limit</div></div><div class="approval-actions"><button class="always" data-action="always">Always allow this action</button><button class="button" data-action="deny">Deny</button><button class="button primary" data-action="approve">${icon('check')}Allow once</button></div></div>`;
}

function workspace() {
  return `<main class="workspace-main"><section class="conversation" aria-label="Orders ETL conversation"><header class="chat-header">${avatar()}<div><div class="row"><h1>Orders ETL</h1><span class="pill">Data engineering</span></div><p>Daily orders, cleaned and delivered.</p></div><span class="spacer"></span>${iconButton('clock','Conversation history')}${iconButton('more','Bot settings')}</header>
    <div class="chat-scroll"><div class="date-separator">Today, October 7</div><article class="user-message"><div class="message-meta"><time>09:41</time><strong>You</strong></div><div class="user-bubble">Clean yesterday’s Azure orders. Keep paid rows with valid amounts, then publish the CSV and summary to <span class="mono" style="font-size:11px">curated</span>. Ask me before running the pipeline.<div><span class="attachment">${icon('file')}orders / 2026-10-06.csv</span></div></div></article>
    <article class="agent-message">${avatar()}<div class="agent-body"><div class="message-meta"><strong>Orders ETL</strong><time>09:41</time></div><p>I’ll validate the source, prepare the transformation, and ask for approval before publishing. You can follow along in my cloud computer.</p><div class="task-card"><div class="row between"><h3>Curate daily orders</h3><span class="pill amber" id="progress-label">2 of 3 complete</span></div><div class="task-step">${icon('checkCircle','green')}Inspect source and validate the schema<time>3 rows</time></div><div class="task-step">${icon('checkCircle','green')}Prepare transformation and preview<time>2 paid</time></div><div class="task-step"><i class="step-pending"></i><span id="pending-step">Run pipeline and publish artifacts</span><time class="amber" id="step-state">Needs approval</time></div></div></div></article>
    <div class="handoff">${icon('arrow')}Orders ETL <span class="quiet">→</span> Reporting Bot <span class="quiet">· Summary will follow after publication</span></div>
    <article class="agent-message">${avatar()}<div class="agent-body"><div class="message-meta"><strong>Orders ETL</strong><time>09:42</time></div><p>The preview contains <strong style="color:var(--text);font-weight:500">2 paid orders totaling $15.75</strong>. One cancelled order is excluded. The script is ready.</p>${approval()}</div></article></div>
    <div class="composer-wrap"><form class="composer" id="composer"><textarea aria-label="Message Orders ETL" placeholder="Message Orders ETL, or @mention another bot…"></textarea><div class="composer-toolbar">${iconButton('attach','Attach a file')}<button class="icon-button" type="button" data-action="mention" aria-label="Mention a bot">@</button><button class="icon-button" type="button" data-toast="Try /routine or /teach in a connected workspace." aria-label="Commands">/</button><span class="spacer"></span><button type="button" class="button subtle" data-toast="Teach a Task would record steps in your cloud computer.">${icon('record')}Teach a Task</button><button type="button" class="button subtle" data-toast="Create Routine would schedule this ETL task.">${icon('clock')}Routine</button>${iconButton('mic','Dictate')}<button class="send" type="submit" aria-label="Send message">${icon('up')}</button></div></form><div class="composer-caption"><span class="row"><i class="dot green"></i>Persistent session · Your files stay here</span><span>Enter to send · Shift Enter for a new line</span></div></div>
    </section><aside class="computer-panel" aria-label="Live Cloud Computer"><div class="row panel-title">${icon('computer')}<h2>Live Cloud Computer</h2><span class="spacer"></span><a class="icon-button" href="?view=computer" title="Open full screen" aria-label="Open cloud computer full screen">${icon('expand')}</a></div><div class="session-name mono">etl-orders-2026-10-06</div><div class="session-line"><i class="dot live"></i>VM alive <span class="quiet">· 2h 14m</span><span class="spacer"></span><span class="pill">Private</span></div>${tabs('Browser')}${miniBrowser()}<div class="control-row"><button class="button" data-action="control">${icon('cursor')}Take control</button><a class="button" href="?view=computer">${icon('expand')}Expand view</a></div>
    <section class="panel-section"><div class="section-heading"><h3 class="row">${icon('terminal')}Terminal</h3><a href="?view=computer&tab=terminal">Open terminal ↗</a></div><div class="terminal-mini"><span class="prompt">agent@etl-orders</span> <span class="quiet">/workspace</span><br><span class="quiet">$</span> python3 -m py_compile etl_orders.py<br><span class="green">✓ Script validated</span><br><span class="quiet">$</span> <span class="cursor"></span></div></section>
    <section class="panel-section"><div class="section-heading"><h3>Workspace files</h3><a href="?view=files">View all ↗</a></div><div class="file-row">${icon('code','violet')}etl_orders.py<span class="pill green" style="margin-left:auto">New</span></div><div class="file-row">${icon('browser','cyan')}preview.html<small>4.2 KB</small></div><div class="file-row">${icon('lock','quiet')}azure.env<small>Protected</small></div></section>
    <div class="panel-foot"><div class="row">${icon('cloud')}Powered by <span class="mono">agentbot_sandbox</span></div><div class="row between" style="margin-top:8px"><span>Ubuntu · Chromium · Python</span><span>1024 × 768</span></div></div></aside></main>`;
}

function expandedHeader() {
  return `<header class="expanded-header"><a class="back row" href="?view=workspace">${icon('back')}Workspace</a><div><h1>Live Cloud Computer</h1><p><i class="dot green"></i><span class="green">VM alive</span> · 2h 14m <span class="quiet"> / </span><span class="mono">etl-orders-2026-10-06</span></p></div><span class="spacer"></span><span class="pill ${isFiles ? 'green' : 'cyan'}"><i class="dot"></i>${isFiles ? 'Task complete' : 'Bot is navigating'}</span><button class="button" data-action="control">${icon('cursor')}Take control</button><button class="button subtle" data-action="share">${icon('share')}Share session</button>${iconButton('refresh','Reset session','reset')}</header>`;
}

function fullBrowser() {
  return `<div class="desktop-view"><div class="desktop-bar">${icon('computer')}Cloud desktop <span class="quiet">/</span> Orders ETL<span class="spacer"></span>${icon('cloud')}Connected <span style="margin-left:10px">09:43</span></div><div class="desktop-browser"><div class="browser-tabbar"><div class="window-dots"><i></i><i></i><i></i></div><span class="browser-tab-title">${icon('chart')}Daily orders · Validation <span class="spacer"></span>×</span><span>+</span></div><div class="browser-chrome">${icon('back')}${icon('arrow')}${icon('refresh')}<div class="browser-url">${icon('lock')}<span>file:///workspace/preview.html</span></div>${icon('more')}</div>
    <div class="full-report"><aside class="report-sidebar"><div class="report-brand">${icon('chart')}ORDERS / DAILY</div><div class="report-nav selected">${icon('grid')}Overview</div><div class="report-nav">${icon('file')}Orders</div><div class="report-nav">${icon('checkCircle')}Validation</div><div class="report-nav">${icon('folder')}Exports</div></aside><div class="report-main"><div class="report-breadcrumb">Workspace / Orders / October 6, 2026</div><div class="row between"><h2>Daily orders</h2><span class="report-badge">✓ Validation passed</span></div><p class="report-subtitle">Curated orders · October 6, 2026 · USD</p><div class="mini-metrics"><div class="mini-metric"><span>Source rows</span><strong>3</strong><em>1 excluded</em></div><div class="mini-metric"><span>Paid orders</span><strong>2</strong><em>Validated</em></div><div class="mini-metric"><span>Total order value</span><strong>$15.75</strong></div></div>
    <div class="report-table-wrap"><div class="report-table-header row between">Curated orders<span>2 records</span></div><table class="full-table"><thead><tr><th>Order ID</th><th>Customer</th><th>Amount</th><th>Currency</th><th>Status</th></tr></thead><tbody><tr><td>1001</td><td>c-9</td><td>12.50</td><td>USD</td><td><span class="paid-badge">Paid</span></td></tr><tr><td>1003</td><td>c-9</td><td>3.25</td><td>USD</td><td><span class="paid-badge">Paid</span></td></tr></tbody></table></div><div class="report-note">${icon('checkCircle')}Cancelled orders excluded. All amounts are valid decimals.</div><div class="agent-cursor">${icon('cursor')}<span>Orders ETL</span></div></div></div></div><div class="desktop-footer">${icon('eye')}Bot is navigating <span class="quiet">· Inspecting the validation preview</span><span class="spacer"></span><i class="dot cyan"></i>Live</div></div>`;
}

function terminal() {
  return `<section class="terminal-pane" id="terminal"><div class="terminal-heading">${icon('terminal')}<span class="tab-label">Terminal 1</span><span class="quiet mono">/workspace</span><span class="spacer"></span><span class="pill green">Exit 0</span>${iconButton('plus','New terminal')}</div><div class="terminal-body"><div><span class="shell-prompt">agent@etl-orders</span><span class="dim">:/workspace</span> $ python3 /workspace/etl_orders.py</div><div><span class="timestamp">09:42:18</span><span class="cyan">EXTRACT</span> <span class="dim">raw/orders/2026-10-06.csv</span> <span class="green">→ 3 rows</span></div><div><span class="timestamp">09:42:18</span><span class="violet">TRANSFORM</span> status=paid · valid decimal <span class="green">→ 2 rows</span></div><div><span class="timestamp">09:42:19</span><span class="cyan">LOAD</span> <span class="dim">curated/orders/2026-10-06.csv</span> <span class="green">201 Created</span></div><div><span class="timestamp">09:42:19</span><span class="cyan">LOAD</span> <span class="dim">curated/orders/2026-10-06.summary.json</span> <span class="green">201 Created</span></div><div><span class="shell-prompt">agent@etl-orders</span><span class="dim">:/workspace</span> $ <span class="cursor"></span></div></div></section>`;
}

function inspector() {
  const events = isFiles ? [
    ['green','Task completed','09:43:08','Published 2 artifacts. Session stays available.'],
    ['green','Summary shared','09:43:07','Orders ETL → Reporting Bot'],
    ['green','Preview inspected','09:43:02','Browser · preview.html'],
    ['green','Artifacts published','09:42:19','CSV + summary · HTTP 201'],
    ['amber','Execution approved','09:42:17','You allowed this action once.'],
  ] : [
    ['cyan','Inspecting preview','09:43:02','Browser · preview.html'],
    ['green','Artifacts published','09:42:19','CSV + summary · HTTP 201'],
    ['green','Pipeline finished','09:42:19','3 rows in → 2 rows out'],
    ['amber','Execution approved','09:42:17','You allowed this action once.'],
    ['green','Script prepared','09:41:54','/workspace/etl_orders.py'],
  ];
  return `<aside class="inspector"><div class="row between"><h2>Session context</h2>${iconButton('more','Session options')}</div><div class="session-card"><div class="row">${avatar()}<div><div class="bot-name">Orders ETL</div><div class="quiet" style="font-size:9px">Data engineering</div></div></div><p>Curate yesterday’s orders and publish a clean CSV with a summary.</p><span class="pill ${isFiles ? 'green' : 'cyan'}"><i class="dot"></i>${isFiles ? 'Completed' : 'Verifying results'}</span></div>
    <div style="margin-top:15px"><div class="detail-pair"><span>Session</span><span class="row"><i class="dot green"></i>Persistent</span></div><div class="detail-pair"><span>Environment</span><span>Ubuntu 24.04</span></div><div class="detail-pair"><span>Working directory</span><span class="mono">/workspace</span></div><div class="detail-pair"><span>Access</span><span class="row">${icon('lock')}Only you</span></div></div>
    <div class="row between timeline-heading"><h2>Activity</h2><span class="pill">Today</span></div><div class="timeline">${events.map(([color,title,time,desc])=>`<article class="event"><i class="event-dot ${color}"></i><div class="row"><h3>${title}</h3><time>${time}</time></div><p>${desc}</p></article>`).join('')}</div>
    <div class="return-chat"><div class="row violet">${icon('chart')}<h3 style="font-size:11px">Reporting Bot</h3></div><p>${isFiles ? 'I have the curated summary. Your daily report is ready to review.' : 'I’m ready to pick up the summary when Orders ETL finishes verification.'}</p><a href="?view=workspace">Return to conversation ${icon('arrow')}</a></div>
    <div class="panel-foot" style="margin-top:18px"><div class="row">${icon('cloud')}Powered by <span class="mono">agentbot_sandbox</span></div></div></aside>`;
}

const summaryCode = `<li>{</li><li>  <span class="code-key">"source"</span>: <span class="code-string">"raw/orders/2026-10-06.csv"</span>,</li><li>  <span class="code-key">"rows_in"</span>: <span class="code-number">3</span>,</li><li>  <span class="code-key">"rows_out"</span>: <span class="code-number">2</span>,</li><li>  <span class="code-key">"output"</span>: <span class="code-string">"curated/orders/2026-10-06.csv"</span></li><li>}</li>`;

function fileContent(file = 'summary') {
  if (file === 'csv') return `<h2>Curated orders</h2><p>2026-10-06.csv · 2 records · UTF-8</p><table class="dark-table"><thead><tr><th>order_id</th><th>customer_id</th><th>amount</th><th>currency</th></tr></thead><tbody><tr><td>1001</td><td>c-9</td><td>12.50</td><td>USD</td></tr><tr><td>1003</td><td>c-9</td><td>3.25</td><td>USD</td></tr></tbody></table><div class="validation-note">${icon('checkCircle')}<div><h3>Ready for downstream reporting</h3><p>Only paid orders with valid decimal amounts are included.</p></div></div>`;
  if (file === 'env') return `<h2>Protected configuration</h2><p>azure.env · Credentials are hidden in this preview.</p><div class="validation-note">${icon('lock')}<div><h3>Two credentials configured</h3><p>RAW_READ_SAS · CURATED_WRITE_SAS</p></div></div>`;
  if (file === 'script') return `<h2>Orders transformation</h2><p>etl_orders.py · Python · Illustrative excerpt</p><div class="code-box"><div class="code-box-header">Paid orders with valid decimal amounts</div><ol class="code-lines"><li><span class="code-key">from</span> decimal <span class="code-key">import</span> Decimal, InvalidOperation</li><li></li><li><span class="code-key">def</span> keep_order(row):</li><li>    <span class="code-key">if</span> row[<span class="code-string">"status"</span>] != <span class="code-string">"paid"</span>:</li><li>        <span class="code-key">return</span> False</li><li>    <span class="code-key">try</span>:</li><li>        <span class="code-key">return</span> Decimal(row[<span class="code-string">"amount"</span>]).is_finite()</li><li>    <span class="code-key">except</span> InvalidOperation:</li><li>        <span class="code-key">return</span> False</li></ol></div>`;
  return `<div class="row between"><h2>Daily orders summary</h2><span class="pill green">${icon('check')}Published</span></div><p>2026-10-06.summary.json · JSON · Created just now</p><div class="preview-metrics"><div><span>Source rows</span><strong>3</strong></div><div><span>Curated rows</span><strong class="cyan">2</strong></div><div><span>Excluded</span><strong>1</strong></div></div><div class="code-box"><div class="code-box-header row between"><span>JSON preview</span><span>UTF-8</span></div><ol class="code-lines">${summaryCode}</ol></div><div class="validation-note">${icon('checkCircle')}<div><h3>Published to Azure Blob Storage</h3><p>etlstore / curated / orders / 2026-10-06.summary.json</p></div></div>`;
}

function fileWorkbench() {
  return `<div class="files-workbench"><aside class="file-tree" aria-label="Workspace files"><div class="tree-heading row between"><span class="eyebrow" style="font-size:9px">Explorer</span>${icon('more')}</div><div class="tree-row">${icon('chevron')}${icon('folder')}workspace</div><button class="tree-row indent" data-file="env">${icon('lock')}azure.env</button><button class="tree-row indent" data-file="script">${icon('code')}etl_orders.py<span class="change">A</span></button><button class="tree-row indent" data-action="open-preview">${icon('browser')}preview.html<span class="change">A</span></button><div class="tree-row indent">${icon('chevron')}${icon('folder')}outputs</div><button class="tree-row deeper" data-file="csv">${icon('file')}2026-10-06.csv<span class="change">A</span></button><button class="tree-row deeper selected" data-file="summary" aria-pressed="true">${icon('file')}2026-10-06.summary.json</button><div class="tree-legend"><span class="green mono">A</span> Added during this session</div></aside><section class="file-preview"><div class="file-preview-header">${icon('file','violet')}<span id="file-tab">2026-10-06.summary.json</span><span class="spacer"></span><button class="icon-button" data-action="download" aria-label="Download selected artifact" title="Download selected artifact">${icon('download')}</button></div><div class="preview-content" id="preview-content">${fileContent()}</div><div class="preview-footer">${icon('folder')}<span id="file-path">/workspace/outputs/2026-10-06.summary.json</span><span class="spacer"></span><span>Read-only</span></div></section></div><div class="artifact-strip">${avatar('chart','violet')}<div><h3>Ready for the next bot</h3><p>Reporting Bot received the curated summary.</p></div><a class="button compact" href="?view=workspace">View handoff ${icon('arrow')}</a></div>`;
}

function expanded() {
  return `<main class="expanded">${expandedHeader()}<div class="expanded-body"><section class="computer-stage"><div class="stage-toolbar">${tabs(isFiles ? 'Filesystem' : 'Browser',true)}<div class="layout-switch" aria-label="Panel layout"><button class="${!isFiles ? 'active' : ''}" data-action="split" title="Browser and terminal" aria-label="Browser and terminal">${icon('split')}</button><button class="${isFiles ? 'active' : ''}" data-action="files" title="Files and activity" aria-label="Files and activity">${icon('columns')}</button></div></div>${isFiles ? fileWorkbench() : fullBrowser()+terminal()}<div class="stage-footer"><span class="row">${icon('shield')}Private session · Workspace preserved</span><span>${isFiles ? '5 files · 2 published artifacts' : 'Browser + Terminal · Fit to panel'}</span></div></section>${inspector()}</div></main>`;
}

document.getElementById('app').innerHTML = `${header()}<div class="shell ${isExpanded ? 'slim-shell' : ''}">${rail()}${isExpanded ? expanded() : workspace()}</div>`;
document.body.dataset.view = isExpanded ? view : 'workspace';
document.querySelectorAll('button:not([type])').forEach(button => button.type = 'button');

let toastTimer;
function toast(message) {
  const element = document.getElementById('toast');
  element.textContent = message;
  element.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('visible'), 3800);
}

let selectedFile = 'summary';
const filenames = { summary: '2026-10-06.summary.json', csv: '2026-10-06.csv', env: 'azure.env', script: 'etl_orders.py' };
document.addEventListener('click', event => {
  const target = event.target.closest('[data-action], [data-toast], [data-file]');
  if (!target) return;
  if (target.dataset.toast) { event.preventDefault(); toast(target.dataset.toast); return; }
  if (target.dataset.file) {
    selectedFile = target.dataset.file;
    document.querySelectorAll('[data-file]').forEach(button => { const selected = button.dataset.file === selectedFile; button.classList.toggle('selected',selected); button.setAttribute('aria-pressed',String(selected)); });
    document.getElementById('preview-content').innerHTML = fileContent(selectedFile);
    document.getElementById('file-tab').textContent = filenames[selectedFile];
    document.getElementById('file-path').textContent = `/workspace/${['summary','csv'].includes(selectedFile) ? 'outputs/' : ''}${filenames[selectedFile]}`;
    return;
  }
  const action = target.dataset.action;
  if (action === 'files') location.search = '?view=files';
  if (action === 'split' || action === 'open-preview') location.search = '?view=computer';
  if (action === 'control') {
    state.control = !state.control;
    target.innerHTML = `${icon(state.control ? 'eye' : 'cursor')}${state.control ? 'Return to bot' : 'Take control'}`;
    toast(state.control ? 'Preview: you have control. The bot is paused.' : 'Preview: control returned to Orders ETL.');
  }
  if (action === 'approve' || action === 'deny' || action === 'always') {
    const allowed = action !== 'deny';
    state.approved = allowed;
    document.getElementById('approval').innerHTML = `<div class="approval-content"><div class="row ${allowed ? 'green' : 'amber'}">${icon(allowed ? 'checkCircle' : 'shield')}<h3>${allowed ? 'Execution approved' : 'Execution denied'}</h3></div><p>${allowed ? 'Preview: the pipeline completed. Two artifacts are ready for review.' : 'The pipeline will not run. You can ask Orders ETL to revise it.'}</p>${allowed ? '<a class="button primary" style="margin-top:12px" href="?view=files">Review published artifacts →</a>' : ''}</div>`;
    document.getElementById('bot-status').textContent = allowed ? 'Completed' : 'Idle';
    document.getElementById('progress-label').textContent = allowed ? '3 of 3 complete' : '2 of 3 complete';
    document.getElementById('step-state').textContent = allowed ? 'Published' : 'Denied';
    document.getElementById('step-state').className = allowed ? 'green' : 'amber';
    toast(action === 'always' ? 'Preview: an approval rule would be saved for this bot and action.' : allowed ? 'Preview only. No cloud operation was executed.' : 'Preview: the action was denied.');
  }
  if (action === 'mention') { const input = document.querySelector('textarea'); input.value += '@Reporting Bot '; input.focus(); }
  if (action === 'collapse') { document.querySelector('.rail').hidden = true; document.querySelector('.shell').style.gridTemplateColumns = 'minmax(0, 1fr)'; toast('Sidebar collapsed. Reload to restore the original mockup.'); }
  if (action === 'share') toast('Share session is a concept control; this prototype has no live session.');
  if (action === 'reset') toast('Reset session would create a fresh sandbox. This mockup preserves its sample data.');
  if (action === 'notifications') toast('1 approval pending · Orders ETL is ready to run.');
  if (action === 'orders') toast('Orders ETL is selected. Review the pending action in the conversation.');
  if (action === 'download') {
    if (!['summary','csv'].includes(selectedFile)) { toast('Only the two sample output artifacts are downloadable.'); return; }
    const data = selectedFile === 'csv' ? 'order_id,customer_id,amount,currency\n1001,c-9,12.50,USD\n1003,c-9,3.25,USD\n' : JSON.stringify({source:'raw/orders/2026-10-06.csv',rows_in:3,rows_out:2,output:'curated/orders/2026-10-06.csv'},null,2)+'\n';
    const url = URL.createObjectURL(new Blob([data], {type:selectedFile === 'csv' ? 'text/csv' : 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = filenames[selectedFile]; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
  }
});

document.getElementById('search').addEventListener('input', event => {
  const query = event.target.value.toLowerCase();
  document.querySelectorAll('[data-bot]').forEach(bot => { bot.hidden = !bot.dataset.bot.toLowerCase().includes(query); bot.style.display = bot.hidden ? 'none' : ''; });
});
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'k') { event.preventDefault(); document.getElementById('search').focus(); }
});
const composer = document.getElementById('composer');
if (composer) {
  composer.addEventListener('submit', event => { event.preventDefault(); const input = composer.querySelector('textarea'); if (!input.value.trim()) { input.focus(); return; } toast('Message preview saved locally for this view. No bot is connected.'); input.value = ''; });
  composer.querySelector('textarea').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); } });
}
if (new URLSearchParams(location.search).get('tab') === 'terminal') {
  document.querySelector('.terminal-pane')?.style.setProperty('box-shadow','0 0 0 1px #00e5ff60');
}
if (new URLSearchParams(location.search).get('tab') === 'activity') {
  document.querySelector('.timeline')?.style.setProperty('border-left','1px solid #00e5ff60');
}
