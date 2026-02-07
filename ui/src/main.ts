import './styles.css'

type ConnectionType = 'OLLAMA' | 'OPENAI' | 'ANTHROPIC' | 'OPENROUTER' | 'OPENAI_COMPAT' | 'LLAMACPP_OPENAI' | 'CUSTOM'
type RunStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
type TabKey = 'garage' | 'cars' | 'tracks' | 'race' | 'leaderboard' | 'history' | 'settings'

type Connection = {
  id: number
  name: string
  type: ConnectionType
  base_url: string
  api_key_env_var?: string | null
  has_stored_api_key?: boolean
}

type ConnectionRuntimeCheck = {
  connection_id: number
  provider_type: ConnectionType
  base_url: string
  auth_source: string
  auth_present: boolean
  discovery_ok: boolean
  latency_ms?: number | null
  models: string[]
  error?: string | null
  hints: string[]
}

type Car = {
  id: number
  name: string
  connection_id: number
  model_name: string
  temperature: number
  top_p: number
}

type SuiteTest = {
  id: number
  order_index: number
  name: string
  system_prompt?: string | null
  user_prompt: string
  expected_constraints?: string | null
  tools_schema_json?: Array<Record<string, unknown>> | null
}

type Suite = {
  id: number
  name: string
  category: string
  description?: string | null
  is_demo: boolean
  tests: SuiteTest[]
}

type Run = {
  id: number
  suite_id: number
  status: RunStatus
  started_at?: string | null
  finished_at?: string | null
  selected_car_ids_json: number[]
  judge_car_id_nullable?: number | null
}

type LeaderboardRow = {
  car_id: number
  car_name: string
  connection_name: string
  model_name: string
  items_total: number
  items_failed: number
  items_partial: number
  avg_ttft_ms: number | null
  avg_latency_ms: number | null
  avg_tokens_per_sec: number | null
  error_rate: number
  avg_assertion_pass_rate: number | null
  avg_judge_overall: number | null
}

type HudMetric = {
  ttft_ms?: number
  latency_ms?: number
  tokens_per_sec?: number
  output_tokens?: number
  estimated?: boolean
}

type ProviderSetting = {
  provider_type: ConnectionType
  max_in_flight: number
  timeout_ms: number
  retry_count: number
  retry_backoff_ms: number
}

type RunItemDetail = {
  id: number
  test_id: number | null
  car_id: number | null
  status: string
  attempt_count: number
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
}

type RunOutputDetail = {
  run_item_id: number
  streamed_text?: string | null
  final_text?: string | null
  raw_provider_payload_json?: Record<string, unknown> | null
}

type RunMetricDetail = {
  run_item_id: number
  ttft_ms?: number | null
  total_latency_ms?: number | null
  output_tokens?: number | null
  tokens_per_sec?: number | null
  error_flag: boolean
}

type RunToolDetail = {
  run_item_id: number
  loop_index: number
  tool_name: string
  status: string
  provider_style: string
}

type RunJudgeDetail = {
  id: number
  run_item_id: number | null
  car_id: number | null
  overall: number
  rationale: string
}

type RunScorecardRow = {
  car_id: number
  car_name: string
  model_name: string
  items_total: number
  items_completed: number
  items_failed: number
  items_partial: number
  error_rate: number
  avg_ttft_ms: number | null
  avg_latency_ms: number | null
  avg_tokens_per_sec: number | null
  assertion_pass_rate: number | null
  avg_judge_overall: number | null
}

type RunComparisonRow = {
  car_id: number
  car_name: string
  model_name: string
  latency_delta_ms: number | null
  tokens_per_sec_delta: number | null
  error_rate_delta: number | null
  assertion_pass_rate_delta: number | null
  judge_overall_delta: number | null
  summary: string
}

type ConnectionDiagnostic = {
  ok: boolean
  latency_ms?: number | null
  models: string[]
  error?: string | null
  checked_at_ms: number
}

type RunDetail = {
  run: Run
  items: RunItemDetail[]
  outputs: RunOutputDetail[]
  metrics: RunMetricDetail[]
  tool_calls: RunToolDetail[]
  judge_results: RunJudgeDetail[]
}

const app = document.querySelector<HTMLDivElement>('#app')
if (!app) {
  throw new Error('Missing app root')
}

const state = {
  activeTab: 'garage' as TabKey,
  connections: [] as Connection[],
  cars: [] as Car[],
  suites: [] as Suite[],
  runs: [] as Run[],
  leaderboard: [] as LeaderboardRow[],
  providerSettings: [] as ProviderSetting[],
  selectedSuiteId: 0,
  selectedCarIds: [] as number[],
  selectedJudgeCarId: 0,
  currentRunId: 0,
  selectedRunDetailId: 0,
  selectedRunDetail: null as RunDetail | null,
  selectedRunScorecard: [] as RunScorecardRow[],
  selectedRunComparison: [] as RunComparisonRow[],
  selectedBaselineRunId: 0,
  telemetryLines: [] as string[],
  telemetryPaused: false,
  hud: new Map<number, HudMetric>(),
  countdownText: '',
  suiteEditorText: '',
  connectionDiagnostics: new Map<number, ConnectionDiagnostic>(),
  connectionRuntimeChecks: new Map<number, ConnectionRuntimeCheck>(),
  carFormConnectionId: 0,
  carConnectionModels: new Map<number, string[]>(),
  carModelsLoadingFor: 0,
  historyStatusFilter: '' as '' | RunStatus,
  historySuiteFilter: 0,
  historyCarFilter: 0,
  notice: 'READY',
  runItemCarMap: new Map<number, number>(),
}

let stream: EventSource | null = null
const RAW_PROXY_BASE = ((import.meta.env.VITE_PROXY_BASE_URL as string | undefined) ?? '').trim()
const PROXY_BASE = RAW_PROXY_BASE ? RAW_PROXY_BASE.replace(/\/$/, '') : ''

const CONNECTION_PRESETS: Record<string, { type: ConnectionType; baseUrl: string; note: string }> = {
  OLLAMA: {
    type: 'OLLAMA',
    baseUrl: 'http://host.docker.internal:11434',
    note: 'Local Ollama endpoint; no API key required.',
  },
  JAN: {
    type: 'LLAMACPP_OPENAI',
    baseUrl: 'http://host.docker.internal:1337',
    note: 'Jan Local API Server (llama.cpp). API key required.',
  },
  OPENAI: {
    type: 'OPENAI',
    baseUrl: 'https://api.openai.com',
    note: 'OpenAI cloud API. Use project API key.',
  },
  ANTHROPIC: {
    type: 'ANTHROPIC',
    baseUrl: 'https://api.anthropic.com',
    note: 'Anthropic Messages API. Uses x-api-key auth.',
  },
  OPENROUTER: {
    type: 'OPENROUTER',
    baseUrl: 'https://openrouter.ai',
    note: 'OpenRouter API. Optional referer/title headers are sent by proxy.',
  },
  OPENAI_COMPAT: {
    type: 'OPENAI_COMPAT',
    baseUrl: 'http://host.docker.internal:1234',
    note: 'OpenAI-compatible local server (LM Studio style).',
  },
  CUSTOM: {
    type: 'CUSTOM',
    baseUrl: 'http://host.docker.internal:1234',
    note: 'Custom OpenAI-compatible endpoint.',
  },
}

function buildUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  if (!PROXY_BASE) {
    return path
  }
  if (path.startsWith('/')) {
    return `${PROXY_BASE}${path}`
  }
  return `${PROXY_BASE}/${path}`
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`${response.status} ${text}`)
  }
  return response.json() as Promise<T>
}

async function ensureCarConnectionModels(connectionId: number, force = false): Promise<string[]> {
  if (!force) {
    const cached = state.carConnectionModels.get(connectionId)
    if (cached && cached.length > 0) {
      return cached
    }
  }

  state.carModelsLoadingFor = connectionId
  try {
    const models = await api<string[]>(`/api/connections/${connectionId}/models`)
    state.carConnectionModels.set(connectionId, models)
    return models
  } finally {
    state.carModelsLoadingFor = 0
  }
}

function html(strings: TemplateStringsArray, ...values: Array<string | number | boolean>): string {
  return strings.reduce((acc, curr, idx) => acc + curr + (values[idx] ?? ''), '')
}

function appendTelemetry(line: string): void {
  state.telemetryLines.push(line)
  if (state.telemetryLines.length > 1200) {
    state.telemetryLines.shift()
  }
  const box = document.getElementById('telemetryBox')
  if (!box) {
    return
  }
  box.textContent = state.telemetryLines.join('\n')
  if (!state.telemetryPaused) {
    box.scrollTop = box.scrollHeight
  }
}

function setNotice(message: string): void {
  state.notice = message
  const notice = document.getElementById('actionNotice')
  if (notice) {
    notice.textContent = message
  }
}

function setCountdown(text: string): void {
  state.countdownText = text
  const node = document.getElementById('countdown')
  if (node) {
    node.textContent = text
  }
}

function simplifyError(input: unknown): string {
  const raw = String(input).replace(/^Error:\s*/i, '')
  const detailMatch = raw.match(/"detail":"([^"]+)"/i)
  if (detailMatch?.[1]) {
    return detailMatch[1]
  }
  return raw
}

function dockerHint(errorMessage?: string | null): string | null {
  const text = (errorMessage ?? '').toLowerCase()
  if (text.includes('invalid host header')) {
    return 'Hint: Jan Local API Server is rejecting host headers. In Jan > Settings > Local API Server, set Trusted Hosts to: host.docker.internal,localhost,127.0.0.1'
  }
  if (text.includes('401') || text.includes('unauthorized')) {
    return 'Hint: this endpoint requires API key auth. Save API key directly in the connection form, then re-test.'
  }
  if (text.includes('windows tip')) {
    return 'Hint: Windows Docker Desktop users should recreate containers after .env/network changes: docker compose up -d --force-recreate'
  }
  if (text.includes('host.docker.internal')) {
    return null
  }
  if (text.includes('proxy runs in docker') || text.includes('all connection attempts failed') || text.includes('connecterror')) {
    return 'Hint: if your model server runs on the host, use http://host.docker.internal:<port> (not localhost).'
  }
  return null
}

function renderConnectionDiagnostic(connectionId: number): string {
  const connection = getConnectionById(connectionId)
  const diagnostic = state.connectionDiagnostics.get(connectionId)
  const runtime = state.connectionRuntimeChecks.get(connectionId)
  const keySummary = connection?.has_stored_api_key
    ? '<div class="conn-model-list">Auth: encrypted key saved</div>'
    : '<div class="conn-error">Auth: no stored key</div>'
  if (!diagnostic) {
    const runtimeSummary = runtime ? `<div class="conn-model-list">Runtime auth source: ${runtime.auth_source}</div>` : ''
    return `<div class="conn-health">Status: untested${keySummary}${runtimeSummary}</div>`
  }

  const checkedAt = new Date(diagnostic.checked_at_ms).toLocaleTimeString()
  const statusClass = diagnostic.ok ? 'ok' : 'error'
  const statusLabel = diagnostic.ok ? 'ONLINE' : 'OFFLINE'
  const modelSummary =
    diagnostic.models.length > 0
      ? `<div class="conn-model-list">Models: ${diagnostic.models.slice(0, 8).join(', ')}${diagnostic.models.length > 8 ? ' ...' : ''}</div>`
      : ''
  const latencySummary = diagnostic.latency_ms ? ` | ${diagnostic.latency_ms}ms` : ''
  const errorSummary = diagnostic.error ? `<div class="conn-error">${diagnostic.error}</div>` : ''
  const hint = dockerHint(diagnostic.error)
  const hintSummary = hint ? `<div class="conn-hint">${hint}</div>` : ''
  const runtimeSummary = runtime
    ? `<div class="conn-model-list">Runtime auth source: ${runtime.auth_source} | auth_present: ${runtime.auth_present}</div>`
    : ''
  const runtimeHints = runtime?.hints?.length
    ? `<div class="conn-hint">${runtime.hints.join(' ')}</div>`
    : ''

  return `<div class="conn-health ${statusClass}">Status: ${statusLabel}${latencySummary} | checked ${checkedAt}${keySummary}${modelSummary}${errorSummary}${runtimeSummary}${runtimeHints}${hintSummary}</div>`
}

function getConnectionById(connectionId: number): Connection | undefined {
  return state.connections.find((connection) => connection.id === connectionId)
}

function getCarById(carId: number): Car | undefined {
  return state.cars.find((car) => car.id === carId)
}

function describeCar(carId: number): string {
  const car = getCarById(carId)
  if (!car) return `profile:${carId}`
  const connection = getConnectionById(car.connection_id)
  const connectionInfo = connection ? `${connection.name} @ ${connection.base_url}` : 'missing connection'
  return `${car.name} (${car.model_name}) via ${connectionInfo}`
}

async function preflightSelectedCars(carIds: number[]): Promise<{ ok: boolean; message?: string }> {
  const selectedCars = carIds.map((carId) => getCarById(carId)).filter((car): car is Car => Boolean(car))
  if (selectedCars.length !== carIds.length) {
    return { ok: false, message: 'One or more selected model profiles no longer exist.' }
  }

  const missingConnectionCars = selectedCars.filter((car) => !getConnectionById(car.connection_id))
  if (missingConnectionCars.length > 0) {
    const names = missingConnectionCars.map((car) => `${car.name} (${car.model_name})`).join(', ')
    return { ok: false, message: `Selected profile has missing connection: ${names}` }
  }

  const connectionIds = Array.from(new Set(selectedCars.map((car) => car.connection_id)))
  const failures: string[] = []
  for (const connectionId of connectionIds) {
    const connection = getConnectionById(connectionId)
    if (!connection) {
      failures.push(`connection:${connectionId} not found`)
      continue
    }
    try {
      setNotice(`[PRECHECK] testing ${connection.name}...`)
      const result = await api<{ ok: boolean; latency_ms?: number; models: string[]; error?: string }>(
        `/api/connections/${connectionId}/test`,
        { method: 'POST' },
      )
      if (!result.ok) {
        failures.push(`${connection.name} @ ${connection.base_url}: ${result.error ?? 'unreachable'}`)
      }
    } catch (error) {
      failures.push(`${connection.name} @ ${connection.base_url}: ${String(error)}`)
    }
  }

  if (failures.length > 0) {
    return { ok: false, message: `Precheck failed. ${failures.join(' | ')}` }
  }
  return { ok: true }
}

async function runCountdown(): Promise<void> {
  for (const tick of ['3', '2', '1', 'GO']) {
    setCountdown(tick)
    await new Promise((resolve) => setTimeout(resolve, 420))
  }
  setCountdown('')
}

function defaultSuiteTemplate(): string {
  return JSON.stringify(
    {
      name: 'My Custom Suite',
      category: 'custom',
      description: 'Replace with your own benchmark suite.',
      tests: [
        {
          order_index: 1,
          name: 'Example Test',
          system_prompt: 'You are a precise assistant.',
          user_prompt: 'Rewrite this sentence in a formal tone.',
          expected_constraints: '2 sentences max.',
          tools_schema_json: null,
        },
      ],
    },
    null,
    2,
  )
}

function suiteById(id: number): Suite | undefined {
  return state.suites.find((suite) => suite.id === id)
}

function loadSuiteIntoEditor(id: number): void {
  const suite = suiteById(id)
  if (!suite) return
  state.suiteEditorText = JSON.stringify(
    {
      name: suite.name,
      category: suite.category,
      description: suite.description ?? '',
      tests: suite.tests.map((test) => ({
        order_index: test.order_index,
        name: test.name,
        system_prompt: test.system_prompt ?? '',
        user_prompt: test.user_prompt,
        expected_constraints: test.expected_constraints ?? '',
        tools_schema_json: test.tools_schema_json ?? null,
      })),
    },
    null,
    2,
  )
}

function fileSafeName(input: string): string {
  const clean = input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return clean || 'llmrace-export'
}

function downloadText(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function refreshData(): Promise<void> {
  const params = new URLSearchParams()
  if (state.historyStatusFilter) params.set('status', state.historyStatusFilter)
  if (state.historySuiteFilter) params.set('suite_id', String(state.historySuiteFilter))
  if (state.historyCarFilter) params.set('car_id', String(state.historyCarFilter))

  const runPath = `/api/runs${params.toString() ? `?${params.toString()}` : ''}`

  const [connections, cars, suites, runs, leaderboard, providerSettings] = await Promise.all([
    api<Connection[]>('/api/connections'),
    api<Car[]>('/api/cars'),
    api<Suite[]>('/api/suites'),
    api<Run[]>(runPath),
    api<{ rows: LeaderboardRow[] }>('/api/leaderboard'),
    api<ProviderSetting[]>('/api/settings/providers'),
  ])

  state.connections = connections
  state.cars = cars
  state.suites = suites
  state.runs = runs
  state.leaderboard = leaderboard.rows
  state.providerSettings = providerSettings
  state.selectedCarIds = state.selectedCarIds.filter((id) => cars.some((car) => car.id === id))
  state.connectionDiagnostics = new Map(
    Array.from(state.connectionDiagnostics.entries()).filter(([id]) => connections.some((connection) => connection.id === id)),
  )
  state.connectionRuntimeChecks = new Map(
    Array.from(state.connectionRuntimeChecks.entries()).filter(([id]) => connections.some((connection) => connection.id === id)),
  )
  state.carConnectionModels = new Map(
    Array.from(state.carConnectionModels.entries()).filter(([id]) => connections.some((connection) => connection.id === id)),
  )
  if (state.carFormConnectionId && !connections.some((connection) => connection.id === state.carFormConnectionId)) {
    state.carFormConnectionId = connections[0]?.id ?? 0
  }

  if (!state.selectedSuiteId && suites.length > 0) {
    state.selectedSuiteId = suites[0].id
    if (!state.suiteEditorText) {
      loadSuiteIntoEditor(suites[0].id)
    }
  }
  if (!state.selectedJudgeCarId && cars.length > 0) {
    state.selectedJudgeCarId = cars[0].id
  } else if (state.selectedJudgeCarId && !cars.some((car) => car.id === state.selectedJudgeCarId)) {
    state.selectedJudgeCarId = cars.length > 0 ? cars[0].id : 0
  }
  if (state.selectedBaselineRunId && !runs.some((run) => run.id === state.selectedBaselineRunId)) {
    state.selectedBaselineRunId = 0
    state.selectedRunComparison = []
  }

  if (!state.suiteEditorText && suites.length === 0) {
    state.suiteEditorText = defaultSuiteTemplate()
  }
}

function renderNav(): string {
  const tabs: Array<[TabKey, string]> = [
    ['garage', 'Connections'],
    ['cars', 'Models'],
    ['tracks', 'Suites'],
    ['race', 'Run'],
    ['leaderboard', 'Comparison'],
    ['history', 'Run History'],
    ['settings', 'Settings'],
  ]

  return tabs
    .map(([key, label]) => `<button class="${state.activeTab === key ? 'active' : ''}" data-tab="${key}">${label}</button>`)
    .join('')
}

function renderGarage(): string {
  const rows = state.connections
    .map(
      (c) => html`<li>
        <strong>${c.name}</strong> <span class="badge">${c.type}</span>
        <div class="muted">${c.base_url}</div>
        ${renderConnectionDiagnostic(c.id)}
        <div class="row" style="margin-top:6px;">
          <button data-action="test-connection" data-id="${c.id}">Test</button>
          <button data-action="verify-runtime" data-id="${c.id}">Verify Runtime</button>
          <button data-action="delete-connection" data-id="${c.id}">Delete</button>
        </div>
      </li>`,
    )
    .join('')

  return html`
    <div class="grid">
      <section class="card" style="grid-column: span 5;">
        <h3>Add Connection</h3>
        <form id="connectionForm" class="stack">
          <label>Name<input name="name" required /></label>
          <label>
            Provider Preset
            <select id="connectionPreset" name="preset">
              <option value="OLLAMA">Ollama</option>
              <option value="JAN">Jan (llama.cpp)</option>
              <option value="OPENAI">OpenAI</option>
              <option value="ANTHROPIC">Anthropic Claude</option>
              <option value="OPENROUTER">OpenRouter</option>
              <option value="OPENAI_COMPAT">OpenAI-compatible local</option>
              <option value="CUSTOM">Custom</option>
            </select>
          </label>
          <label>
            Type
            <select name="type">
              <option value="OLLAMA">OLLAMA</option>
              <option value="OPENAI">OPENAI</option>
              <option value="ANTHROPIC">ANTHROPIC</option>
              <option value="OPENROUTER">OPENROUTER</option>
              <option value="OPENAI_COMPAT">OPENAI_COMPAT</option>
              <option value="LLAMACPP_OPENAI">LLAMACPP_OPENAI</option>
              <option value="CUSTOM">CUSTOM</option>
            </select>
          </label>
          <label>Base URL<input name="base_url" id="connectionBaseUrl" placeholder="http://host.docker.internal:11434" required /></label>
          <label>API Key (stored encrypted)<input name="api_key" type="password" placeholder="Paste API key (optional for local no-auth endpoints)" /></label>
          <div class="muted">
            <span id="connectionPresetNote">${CONNECTION_PRESETS.OLLAMA.note}</span>
          </div>
          <button class="primary" type="submit">Save Connection</button>
        </form>
      </section>
      <section class="card" style="grid-column: span 7;">
        <h3>Connection List</h3>
        <ul class="list">${rows || '<li>No connections yet.</li>'}</ul>
      </section>
    </div>
  `
}

function renderCars(): string {
  if (state.connections.length === 0) {
    return html`
      <div class="grid">
        <section class="card" style="grid-column: span 12;">
          <h3>Add Model Profile</h3>
          <p class="muted">Add at least one connection first, then create model profiles from discovered models.</p>
        </section>
      </div>
    `
  }

  if (!state.carFormConnectionId || !state.connections.some((c) => c.id === state.carFormConnectionId)) {
    state.carFormConnectionId = state.connections[0].id
  }

  const connectionOptions = state.connections
    .map((c) => `<option value="${c.id}" ${c.id === state.carFormConnectionId ? 'selected' : ''}>${c.name} (${c.type})</option>`)
    .join('')
  const modelOptions = state.carConnectionModels.get(state.carFormConnectionId) ?? []
  const modelField =
    modelOptions.length > 0
      ? `<label>Model<select name="model_name" id="carModelSelect" required>${modelOptions.map((m) => `<option value="${m}">${m}</option>`).join('')}</select></label>`
      : '<label>Model<input name="model_name" id="carModelInput" required placeholder="Load models or enter manually" /></label>'
  const loadingText = state.carModelsLoadingFor === state.carFormConnectionId ? 'Loading models...' : 'Load Models'
  const modelHint =
    modelOptions.length > 0
      ? `<div class="muted">${modelOptions.length} models loaded for selected connection.</div>`
      : '<div class="muted">Click "Load Models" for selected connection, or type model manually.</div>'

  const rows = state.cars
    .map((c) => {
      const connection = getConnectionById(c.connection_id)
      return html`<li>
        <strong>${c.name}</strong> <span class="badge">${c.model_name}</span>
        <div class="muted">temp ${c.temperature} | top_p ${c.top_p}</div>
        <div class="muted">${connection ? `${connection.name} @ ${connection.base_url}` : 'connection missing'}</div>
        <div class="row" style="margin-top:6px;">
          <button data-action="delete-car" data-id="${c.id}">Delete</button>
        </div>
      </li>`
    })
    .join('')

  return html`
    <div class="grid">
      <section class="card" style="grid-column: span 5;">
        <h3>Add Model Profile</h3>
        <form id="carForm" class="stack">
          <label>Profile Name<input name="name" required /></label>
          <label>Connection<select name="connection_id" id="carConnectionSelect" required>${connectionOptions}</select></label>
          <div class="row">
            <button type="button" id="loadCarModelsBtn">${loadingText}</button>
          </div>
          ${modelField}
          ${modelHint}
          <label>Temperature<input type="number" name="temperature" value="0.7" step="0.1" /></label>
          <label>Top P<input type="number" name="top_p" value="1" step="0.1" /></label>
          <button class="primary" type="submit">Save Profile</button>
        </form>
      </section>
      <section class="card" style="grid-column: span 7;">
        <h3>Model Profiles</h3>
        <ul class="list">${rows || '<li>No model profiles yet.</li>'}</ul>
      </section>
    </div>
  `
}

function renderTracks(): string {
  const suites = state.suites
    .map((suite) => {
      const selected = suite.id === state.selectedSuiteId ? 'active-row' : ''
      return html`<li class="${selected}">
        <strong>${suite.name}</strong> <span class="badge">${suite.category}</span> ${suite.is_demo ? '<span class="badge">DEMO</span>' : ''}
        <div class="muted">${suite.description ?? ''}</div>
        <div class="muted">${suite.tests.length} tests</div>
        <div class="row" style="margin-top:6px;">
          <button data-action="load-suite" data-id="${suite.id}">Load</button>
          <button data-action="export-suite" data-id="${suite.id}">Export</button>
          <button data-action="delete-suite" data-id="${suite.id}">Delete</button>
        </div>
      </li>`
    })
    .join('')

  const selectedSuite = state.suites.find((s) => s.id === state.selectedSuiteId)
  const testRows = (selectedSuite?.tests ?? [])
    .map((t) => `<tr><td>${t.order_index}</td><td>${t.name}</td><td>${t.expected_constraints ?? '-'}</td><td>${t.tools_schema_json ? 'yes' : '-'}</td></tr>`)
    .join('')

  return html`
    <div class="grid">
      <section class="card" style="grid-column: span 5;">
        <h3>Suites</h3>
        <ul class="list">${suites || '<li>No suites.</li>'}</ul>
      </section>
      <section class="card" style="grid-column: span 7;">
        <h3>Suite Detail</h3>
        <label>
          Select Suite
          <select id="suiteSelect">
            ${state.suites.map((s) => `<option value="${s.id}" ${s.id === state.selectedSuiteId ? 'selected' : ''}>${s.name}</option>`).join('')}
          </select>
        </label>
        <table class="table" style="margin-top:10px;">
          <thead><tr><th>#</th><th>Test</th><th>Constraints</th><th>Tools</th></tr></thead>
          <tbody>${testRows || '<tr><td colspan="4">No tests</td></tr>'}</tbody>
        </table>
      </section>
    </div>
    <section class="card" style="margin-top:12px;">
      <h3>Suite JSON Editor</h3>
      <p class="muted">Use JSON to create or update your benchmark suites quickly.</p>
      <textarea id="suiteEditor" style="min-height:320px;">${state.suiteEditorText || defaultSuiteTemplate()}</textarea>
      <div class="row" style="margin-top:10px;">
        <button class="primary" id="createSuiteBtn">Create New Suite</button>
        <button id="updateSuiteBtn">Update Selected Suite</button>
        <button id="editorTemplateBtn">Load Template</button>
      </div>
    </section>
  `
}

function renderHud(): string {
  if (state.hud.size === 0) {
    return '<div class="muted">Run metrics will appear here.</div>'
  }

  return Array.from(state.hud.entries())
    .map(([itemId, metric]) => {
      const latency = metric.latency_ms ? `${metric.latency_ms} ms` : '-'
      const ttft = metric.ttft_ms ? `${metric.ttft_ms} ms` : '-'
      const tps = metric.tokens_per_sec ? metric.tokens_per_sec.toFixed(2) : '-'
      const tokens = metric.output_tokens ?? '-'
      const est = metric.estimated ? 'est' : 'exact'
      return html`<div class="hud-item">
        <div class="muted">Run Item ${itemId}</div>
        <div class="value">${latency}</div>
        <div class="muted">TTFT ${ttft}</div>
        <div class="muted">${tps} tok/s | ${tokens} ${est}</div>
      </div>`
    })
    .join('')
}

function renderRace(): string {
  const suiteOptions = state.suites
    .map((s) => `<option value="${s.id}" ${state.selectedSuiteId === s.id ? 'selected' : ''}>${s.name}</option>`)
    .join('')
  const carChecks = state.cars
    .map((c) => {
      const checked = state.selectedCarIds.includes(c.id) ? 'checked' : ''
      const connection = getConnectionById(c.connection_id)
      const connectionSummary = connection ? `${connection.name} @ ${connection.base_url}` : 'connection missing'
      const diagnostic = connection ? state.connectionDiagnostics.get(connection.id) : null
      const health = diagnostic
        ? diagnostic.ok
          ? '<span class="status-ok">online</span>'
          : '<span class="status-error">offline</span>'
        : '<span class="status-unknown">untested</span>'
      const warning = connection ? '' : '<span class="warn">missing connection</span>'
      return `<label class="car-option"><input type="checkbox" data-car-id="${c.id}" ${checked} /> <span>${c.name} (${c.model_name})</span><div class="muted">${connectionSummary} ${warning} ${health}</div></label>`
    })
    .join('')
  const judgeOptions = state.cars
    .map((c) => `<option value="${c.id}" ${state.selectedJudgeCarId === c.id ? 'selected' : ''}>${c.name}</option>`)
    .join('')

  return html`
    <div class="grid">
      <section class="card" style="grid-column: span 4;">
        <h3>Start Run</h3>
        <label>Suite<select id="raceSuiteSelect">${suiteOptions}</select></label>
        <div class="stack" style="margin-top:10px;">
          <strong>Models</strong>
          ${carChecks || '<div class="muted">Create model profiles first.</div>'}
        </div>
        <label style="margin-top:10px;">Judge Model<select id="judgeSelect">${judgeOptions}</select></label>
        <div class="row" style="margin-top:12px;">
          <button class="primary" id="startRaceBtn">Start Run</button>
          <button id="judgeRunBtn">Judge Run</button>
        </div>
        <div id="countdown" class="countdown">${state.countdownText}</div>
      </section>

      <section class="card" style="grid-column: span 8;">
        <h3>Runtime Console</h3>
        <div class="row" style="margin-bottom:8px;">
          <button id="toggleScrollBtn">${state.telemetryPaused ? 'Resume Scroll' : 'Pause Scroll'}</button>
          <button id="clearTelemetryBtn">Clear</button>
          <span class="muted">Run ID: ${state.currentRunId || '-'}</span>
        </div>
        <pre id="telemetryBox" class="telemetry">${state.telemetryLines.join('\n')}</pre>
      </section>
    </div>

    <section class="card" style="margin-top:12px;">
      <h3>Metrics</h3>
      <div class="hud">${renderHud()}</div>
    </section>
  `
}

function miniChart(rows: LeaderboardRow[], key: 'avg_latency_ms' | 'avg_tokens_per_sec'): string {
  const values = rows.map((r) => r[key] ?? 0)
  const max = Math.max(1, ...values)
  return rows
    .map((row) => {
      const value = row[key] ?? 0
      const width = Math.round((value / max) * 100)
      const label = key === 'avg_latency_ms' ? `${Math.round(value)} ms` : `${value.toFixed(2)} tok/s`
      return `<div style="margin-bottom:6px;"><div class="muted">${row.car_name}: ${label}</div><div style="height:8px;background:#0c1733;border-radius:99px;"><div style="width:${width}%;height:8px;background:linear-gradient(90deg,var(--neon-cyan),var(--neon-blue));border-radius:99px;"></div></div></div>`
    })
    .join('')
}

function renderLeaderboard(): string {
  const rows = state.leaderboard
  const tableRows = rows
    .map(
      (r) => `<tr>
        <td>${r.car_name}</td>
        <td>${r.model_name}</td>
        <td>${r.items_total}</td>
        <td>${r.items_total > 0 ? (((r.items_total - r.items_failed) / r.items_total) * 100).toFixed(1) : '-'}%</td>
        <td>${r.avg_ttft_ms ? r.avg_ttft_ms.toFixed(1) : '-'}</td>
        <td>${r.avg_latency_ms ? r.avg_latency_ms.toFixed(1) : '-'}</td>
        <td>${r.avg_tokens_per_sec ? r.avg_tokens_per_sec.toFixed(2) : '-'}</td>
        <td>${(r.error_rate * 100).toFixed(1)}%</td>
        <td>${r.avg_assertion_pass_rate != null ? (r.avg_assertion_pass_rate * 100).toFixed(1) : '-'}%</td>
        <td>${r.avg_judge_overall ? r.avg_judge_overall.toFixed(2) : '-'}</td>
      </tr>`,
    )
    .join('')

  return html`
    <div class="grid">
      <section class="card" style="grid-column: span 8;">
        <h3>Model Comparison</h3>
        <table class="table">
          <thead><tr><th>Profile</th><th>Model</th><th>Items</th><th>Success</th><th>TTFT</th><th>Latency</th><th>Tok/s</th><th>Error</th><th>Checks</th><th>Judge</th></tr></thead>
          <tbody>${tableRows || '<tr><td colspan="10">No runs yet.</td></tr>'}</tbody>
        </table>
      </section>
      <section class="card" style="grid-column: span 4;">
        <h3>Latency Trend</h3>
        <div class="chart">${miniChart(rows, 'avg_latency_ms')}</div>
      </section>
    </div>
    <section class="card" style="margin-top:12px;">
      <h3>Tokens/sec Trend</h3>
      <div class="chart">${miniChart(rows, 'avg_tokens_per_sec')}</div>
    </section>
  `
}

function renderHistory(): string {
  const statusOptions = ['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED']
    .map((status) => `<option value="${status}" ${state.historyStatusFilter === status ? 'selected' : ''}>${status}</option>`)
    .join('')
  const suiteOptions = state.suites
    .map((suite) => `<option value="${suite.id}" ${state.historySuiteFilter === suite.id ? 'selected' : ''}>${suite.name}</option>`)
    .join('')
  const carOptions = state.cars
    .map((car) => `<option value="${car.id}" ${state.historyCarFilter === car.id ? 'selected' : ''}>${car.name}</option>`)
    .join('')

  const rows = state.runs
    .map(
      (r) => `<tr>
        <td>${r.id}</td>
        <td>${r.status}</td>
        <td>${r.suite_id}</td>
        <td>${r.selected_car_ids_json.join(', ')}</td>
        <td>${r.started_at ?? '-'}</td>
        <td>${r.finished_at ?? '-'}</td>
        <td class="row">
          <button data-action="inspect-run" data-id="${r.id}">Inspect</button>
          <button data-action="export-run" data-id="${r.id}">Export</button>
        </td>
      </tr>`,
    )
    .join('')

  const detail = renderRunDetail()

  return html`
    <section class="card">
      <h3>Run History</h3>
      <div class="row" style="margin-bottom:10px;">
        <label>Status<select id="historyStatus"><option value="">All</option>${statusOptions}</select></label>
        <label>Suite<select id="historySuite"><option value="0">All</option>${suiteOptions}</select></label>
        <label>Model<select id="historyCar"><option value="0">All</option>${carOptions}</select></label>
        <button id="historyApply">Apply Filters</button>
        <button id="historyReset">Reset</button>
      </div>
      <table class="table">
        <thead><tr><th>Run</th><th>Status</th><th>Suite</th><th>Models</th><th>Started</th><th>Finished</th><th>Actions</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="7">No runs.</td></tr>'}</tbody>
      </table>
    </section>
    ${detail}
  `
}

function renderRunDetail(): string {
  const detail = state.selectedRunDetail
  if (!detail) {
    return ''
  }

  const itemRows = detail.items
    .map((item) => {
      const output = detail.outputs.find((o) => o.run_item_id === item.id)
      const metric = detail.metrics.find((m) => m.run_item_id === item.id)
      const toolCount = detail.tool_calls.filter((tool) => tool.run_item_id === item.id).length
      const assertions = (output?.raw_provider_payload_json as { assertions?: { passed?: number; total?: number } } | undefined)
        ?.assertions
      const assertionText =
        assertions && typeof assertions.total === 'number'
          ? `${assertions.passed ?? 0}/${assertions.total}`
          : '-'
      const preview = (output?.final_text || output?.streamed_text || '').slice(0, 240).replace(/\n/g, ' ')
      const previewSafe = preview ? `${preview}${preview.length >= 240 ? '...' : ''}` : '-'
      return `<tr>
        <td>${item.id}</td>
        <td>${item.test_id ?? '-'}</td>
        <td>${item.car_id ?? '-'}</td>
        <td>${item.status}</td>
        <td>${metric?.ttft_ms ?? '-'}</td>
        <td>${metric?.total_latency_ms ?? '-'}</td>
        <td>${metric?.tokens_per_sec ? metric.tokens_per_sec.toFixed(2) : '-'}</td>
        <td>${toolCount}</td>
        <td>${assertionText}</td>
        <td>${item.error_message ?? '-'}</td>
        <td>${previewSafe}</td>
      </tr>`
    })
    .join('')

  const judgeRows = detail.judge_results
    .map(
      (row) =>
        `<tr><td>${row.id}</td><td>${row.run_item_id ?? '-'}</td><td>${row.car_id ?? '-'}</td><td>${row.overall.toFixed(2)}</td><td>${row.rationale}</td></tr>`,
    )
    .join('')

  const scorecardRows = state.selectedRunScorecard
    .map((row) => {
      const successRate = row.items_total > 0 ? (((row.items_total - row.items_failed) / row.items_total) * 100).toFixed(1) : '-'
      return `<tr>
        <td>${row.car_name}</td>
        <td>${row.model_name}</td>
        <td>${row.items_total}</td>
        <td>${row.items_completed}</td>
        <td>${row.items_failed}</td>
        <td>${row.items_partial}</td>
        <td>${successRate}%</td>
        <td>${(row.error_rate * 100).toFixed(1)}%</td>
        <td>${row.avg_latency_ms != null ? row.avg_latency_ms.toFixed(1) : '-'}</td>
        <td>${row.avg_tokens_per_sec != null ? row.avg_tokens_per_sec.toFixed(2) : '-'}</td>
        <td>${row.assertion_pass_rate != null ? (row.assertion_pass_rate * 100).toFixed(1) : '-'}%</td>
        <td>${row.avg_judge_overall != null ? row.avg_judge_overall.toFixed(2) : '-'}</td>
      </tr>`
    })
    .join('')

  const baselineOptions = state.runs
    .filter((run) => run.id !== detail.run.id)
    .map((run) => `<option value="${run.id}" ${run.id === state.selectedBaselineRunId ? 'selected' : ''}>Run ${run.id} (${run.status})</option>`)
    .join('')

  const formatDelta = (value: number | null, suffix: string): string => {
    if (value == null) return '-'
    const cls = value > 0 ? 'delta-plus' : value < 0 ? 'delta-minus' : 'delta-neutral'
    const sign = value > 0 ? '+' : ''
    return `<span class="${cls}">${sign}${value.toFixed(2)}${suffix}</span>`
  }

  const comparisonRows = state.selectedRunComparison
    .map((row) => {
      const summaryClass = row.summary === 'improved' ? 'status-ok' : row.summary === 'regressed' ? 'status-error' : 'status-unknown'
      return `<tr>
        <td>${row.car_name}</td>
        <td>${row.model_name}</td>
        <td>${formatDelta(row.latency_delta_ms, ' ms')}</td>
        <td>${formatDelta(row.tokens_per_sec_delta, ' tok/s')}</td>
        <td>${formatDelta(row.error_rate_delta != null ? row.error_rate_delta * 100 : null, '%')}</td>
        <td>${formatDelta(row.assertion_pass_rate_delta != null ? row.assertion_pass_rate_delta * 100 : null, '%')}</td>
        <td>${formatDelta(row.judge_overall_delta, '')}</td>
        <td><span class="${summaryClass}">${row.summary}</span></td>
      </tr>`
    })
    .join('')

  return html`
    <section class="card" style="margin-top:12px;">
      <h3>Run ${detail.run.id} Detail</h3>
      <div class="row" style="margin-bottom:8px;">
        <span class="badge">Status ${detail.run.status}</span>
        <span class="muted">Suite ${detail.run.suite_id}</span>
      </div>
      <table class="table">
        <thead>
          <tr><th>Item</th><th>Test</th><th>Model</th><th>Status</th><th>TTFT</th><th>Latency</th><th>Tok/s</th><th>Tools</th><th>Checks</th><th>Error</th><th>Output Preview</th></tr>
        </thead>
        <tbody>${itemRows || '<tr><td colspan="11">No run items.</td></tr>'}</tbody>
      </table>
      <h3 style="margin-top:14px;">Judge Results</h3>
      <table class="table">
        <thead><tr><th>ID</th><th>Run Item</th><th>Model</th><th>Overall</th><th>Rationale</th></tr></thead>
        <tbody>${judgeRows || '<tr><td colspan="5">No judge results.</td></tr>'}</tbody>
      </table>
      <h3 style="margin-top:14px;">Run Scorecard</h3>
      <table class="table">
        <thead><tr><th>Profile</th><th>Model</th><th>Items</th><th>Completed</th><th>Failed</th><th>Partial</th><th>Success</th><th>Error</th><th>Latency</th><th>Tok/s</th><th>Checks</th><th>Judge</th></tr></thead>
        <tbody>${scorecardRows || '<tr><td colspan="12">No scorecard data.</td></tr>'}</tbody>
      </table>
      <h3 style="margin-top:14px;">Baseline Comparison</h3>
      <div class="row" style="margin-bottom:8px;">
        <label>Baseline Run
          <select id="baselineRunSelect">
            <option value="0">Select baseline</option>
            ${baselineOptions}
          </select>
        </label>
        <button id="compareRunBtn">Compare</button>
      </div>
      <table class="table">
        <thead><tr><th>Profile</th><th>Model</th><th>Latency Δ</th><th>Tok/s Δ</th><th>Error Δ</th><th>Checks Δ</th><th>Judge Δ</th><th>Summary</th></tr></thead>
        <tbody>${comparisonRows || '<tr><td colspan="8">Pick a baseline run to compare regression/improvement.</td></tr>'}</tbody>
      </table>
    </section>
  `
}

function renderSettings(): string {
  const rows = state.providerSettings
    .map((setting) => {
      const key = setting.provider_type
      return `<tr>
        <td>${setting.provider_type}</td>
        <td><input type="number" data-setting="${key}" data-field="max_in_flight" value="${setting.max_in_flight}" min="1" /></td>
        <td><input type="number" data-setting="${key}" data-field="timeout_ms" value="${setting.timeout_ms}" min="1000" step="1000" /></td>
        <td><input type="number" data-setting="${key}" data-field="retry_count" value="${setting.retry_count}" min="0" /></td>
        <td><input type="number" data-setting="${key}" data-field="retry_backoff_ms" value="${setting.retry_backoff_ms}" min="0" step="50" /></td>
      </tr>`
    })
    .join('')

  return html`
    <section class="card">
      <h3>Provider Runtime Settings</h3>
      <p class="muted">Tune stability/throughput per provider family.</p>
      <table class="table">
        <thead><tr><th>Provider</th><th>Max In Flight</th><th>Timeout (ms)</th><th>Retries</th><th>Backoff (ms)</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5">No settings available.</td></tr>'}</tbody>
      </table>
      <div class="row" style="margin-top:10px;">
        <button class="primary" id="saveSettingsBtn">Save Settings</button>
      </div>
    </section>
  `
}

function renderMain(): string {
  switch (state.activeTab) {
    case 'garage':
      return renderGarage()
    case 'cars':
      return renderCars()
    case 'tracks':
      return renderTracks()
    case 'race':
      return renderRace()
    case 'leaderboard':
      return renderLeaderboard()
    case 'history':
      return renderHistory()
    case 'settings':
      return renderSettings()
    default:
      return '<div class="card">Unknown tab.</div>'
  }
}

function renderApp(): void {
  app.innerHTML = html`
    <header class="header">
      <div>
        <h1 class="brand">LLM BENCH CONSOLE</h1>
        <p class="subtitle">Build custom suites, run local LLM benchmarks, inspect outputs, and compare reliability.</p>
      </div>
      <div class="muted">Sequential execution | SSE stream | SQLite persistence</div>
    </header>
    <div id="actionNotice" class="notice">${state.notice}</div>
    <nav class="nav">${renderNav()}</nav>
    <main>${renderMain()}</main>
  `

  wireEvents()
}

function wireEvents(): void {
  document.querySelectorAll<HTMLButtonElement>('[data-tab]').forEach((button) => {
    button.onclick = () => {
      state.activeTab = button.dataset.tab as TabKey
      renderApp()
    }
  })

  const connectionForm = document.getElementById('connectionForm') as HTMLFormElement | null
  if (connectionForm) {
    const presetSelect = document.getElementById('connectionPreset') as HTMLSelectElement | null
    const typeSelect = connectionForm.querySelector('select[name="type"]') as HTMLSelectElement | null
    const baseUrlInput = document.getElementById('connectionBaseUrl') as HTMLInputElement | null
    const presetNote = document.getElementById('connectionPresetNote') as HTMLSpanElement | null
    const applyPreset = (presetKey: string) => {
      const preset = CONNECTION_PRESETS[presetKey] ?? CONNECTION_PRESETS.CUSTOM
      if (typeSelect) typeSelect.value = preset.type
      if (baseUrlInput) baseUrlInput.value = preset.baseUrl
      if (presetNote) presetNote.textContent = preset.note
    }
    applyPreset(presetSelect?.value ?? 'OLLAMA')
    if (presetSelect) {
      presetSelect.onchange = () => applyPreset(presetSelect.value)
    }

    connectionForm.onsubmit = async (ev) => {
      ev.preventDefault()
      const form = new FormData(connectionForm)
      await api('/api/connections', {
        method: 'POST',
        body: JSON.stringify({
          name: String(form.get('name')),
          type: String(form.get('type')),
          base_url: String(form.get('base_url')),
          api_key: String(form.get('api_key') ?? '') || null,
        }),
      })
      await refreshAndRender('Connection saved.')
      setNotice('Connection saved.')
    }
  }

  document.querySelectorAll<HTMLButtonElement>('[data-action="test-connection"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      setNotice(`[CONNECTION ${id}] testing...`)
      try {
        const result = await api<{ ok: boolean; latency_ms?: number; models: string[]; error?: string }>(`/api/connections/${id}/test`, {
          method: 'POST',
        })
        state.connectionDiagnostics.set(id, {
          ok: result.ok,
          latency_ms: result.latency_ms ?? null,
          models: result.models ?? [],
          error: result.error ?? null,
          checked_at_ms: Date.now(),
        })
        const msg = `[CONNECTION ${id}] ok=${result.ok} latency=${result.latency_ms ?? '-'}ms models=${result.models.join(',') || '-'} ${result.error ?? ''}`
        appendTelemetry(msg)
        setNotice(msg)
        renderApp()
      } catch (error) {
        const prettyError = simplifyError(error)
        state.connectionDiagnostics.set(id, {
          ok: false,
          models: [],
          error: prettyError,
          checked_at_ms: Date.now(),
        })
        const msg = `[CONNECTION ${id}] test failed: ${prettyError}`
        appendTelemetry(msg)
        setNotice(msg)
        alert(msg)
        renderApp()
      }
    }
  })

  document.querySelectorAll<HTMLButtonElement>('[data-action="verify-runtime"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      setNotice(`[CONNECTION ${id}] runtime verify...`)
      try {
        const runtime = await api<ConnectionRuntimeCheck>(`/api/connections/${id}/verify-runtime`, { method: 'POST' })
        state.connectionRuntimeChecks.set(id, runtime)
        const message = `[CONNECTION ${id}] runtime auth=${runtime.auth_source} present=${runtime.auth_present} discovery_ok=${runtime.discovery_ok} models=${runtime.models.join(',') || '-'}`
        appendTelemetry(message)
        setNotice(message)
        renderApp()
      } catch (error) {
        const prettyError = simplifyError(error)
        const message = `[CONNECTION ${id}] runtime verify failed: ${prettyError}`
        appendTelemetry(message)
        setNotice(message)
        alert(message)
      }
    }
  })

  document.querySelectorAll<HTMLButtonElement>('[data-action="delete-connection"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      if (!confirm(`Delete connection ${id}?`)) return
      await api(`/api/connections/${id}`, { method: 'DELETE' })
      state.connectionDiagnostics.delete(id)
      state.connectionRuntimeChecks.delete(id)
      await refreshAndRender(`Connection ${id} deleted.`)
    }
  })

  const carForm = document.getElementById('carForm') as HTMLFormElement | null
  if (carForm) {
    const carConnectionSelect = document.getElementById('carConnectionSelect') as HTMLSelectElement | null
    const loadCarModelsBtn = document.getElementById('loadCarModelsBtn') as HTMLButtonElement | null

    if (carConnectionSelect) {
      carConnectionSelect.onchange = () => {
        state.carFormConnectionId = Number(carConnectionSelect.value)
        renderApp()
      }
    }

    if (loadCarModelsBtn) {
      loadCarModelsBtn.onclick = async () => {
        const connectionId = carConnectionSelect ? Number(carConnectionSelect.value) : state.carFormConnectionId
        if (!connectionId) return
        setNotice(`[CAR FORM] loading models for connection ${connectionId}...`)
        try {
          const models = await ensureCarConnectionModels(connectionId, true)
          const message = `[CAR FORM] loaded ${models.length} models for connection ${connectionId}`
          appendTelemetry(message)
          setNotice(message)
          renderApp()
        } catch (error) {
          const prettyError = simplifyError(error)
          const message = `[CAR FORM] model load failed for connection ${connectionId}: ${prettyError}`
          appendTelemetry(message)
          setNotice(message)
          alert(message)
          renderApp()
        }
      }
    }

    carForm.onsubmit = async (ev) => {
      ev.preventDefault()
      const form = new FormData(carForm)
      const connectionId = Number(form.get('connection_id'))
      state.carFormConnectionId = connectionId
      await api('/api/cars', {
        method: 'POST',
        body: JSON.stringify({
          name: String(form.get('name')),
          connection_id: connectionId,
          model_name: String(form.get('model_name')),
          temperature: Number(form.get('temperature')),
          top_p: Number(form.get('top_p')),
        }),
      })
      await refreshAndRender('Model profile added.')
      setNotice('Model profile added.')
    }
  }

  document.querySelectorAll<HTMLButtonElement>('[data-action="delete-car"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      if (!confirm(`Delete model profile ${id}?`)) return
      await api(`/api/cars/${id}`, { method: 'DELETE' })
      state.selectedCarIds = state.selectedCarIds.filter((carId) => carId !== id)
      await refreshAndRender(`Model profile ${id} deleted.`)
    }
  })

  const suiteSelect = document.getElementById('suiteSelect') as HTMLSelectElement | null
  if (suiteSelect) {
    suiteSelect.onchange = () => {
      state.selectedSuiteId = Number(suiteSelect.value)
      loadSuiteIntoEditor(state.selectedSuiteId)
      renderApp()
    }
  }

  const suiteEditor = document.getElementById('suiteEditor') as HTMLTextAreaElement | null
  if (suiteEditor) {
    suiteEditor.oninput = () => {
      state.suiteEditorText = suiteEditor.value
    }
  }

  const parseSuiteEditor = (): {
    name: string
    category: string
    description?: string | null
    tests: Array<{
      order_index: number
      name: string
      system_prompt?: string | null
      user_prompt: string
      expected_constraints?: string | null
      tools_schema_json?: Array<Record<string, unknown>> | null
    }>
  } => {
    const parsed = JSON.parse(state.suiteEditorText)
    if (!parsed || typeof parsed !== 'object') throw new Error('Editor JSON must be an object.')
    const suite = parsed as Record<string, unknown>
    if (typeof suite.name !== 'string' || !suite.name.trim()) throw new Error('Suite JSON requires non-empty "name".')
    if (typeof suite.category !== 'string' || !suite.category.trim()) throw new Error('Suite JSON requires non-empty "category".')
    if (!Array.isArray(suite.tests) || suite.tests.length === 0) throw new Error('Suite JSON requires non-empty "tests" array.')
    return suite as any
  }

  const createSuiteBtn = document.getElementById('createSuiteBtn') as HTMLButtonElement | null
  if (createSuiteBtn) {
    createSuiteBtn.onclick = async () => {
      try {
        const payload = parseSuiteEditor()
        const created = await api<Suite>('/api/suites', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        state.selectedSuiteId = created.id
        loadSuiteIntoEditor(created.id)
        await refreshAndRender(`Suite ${created.name} created.`)
      } catch (error) {
        const msg = `Suite create failed: ${String(error)}`
        appendTelemetry(`[SUITE] ${msg}`)
        alert(msg)
      }
    }
  }

  const updateSuiteBtn = document.getElementById('updateSuiteBtn') as HTMLButtonElement | null
  if (updateSuiteBtn) {
    updateSuiteBtn.onclick = async () => {
      if (!state.selectedSuiteId) {
        alert('Select a suite first.')
        return
      }
      try {
        const payload = parseSuiteEditor()
        await api<Suite>(`/api/suites/${state.selectedSuiteId}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
        await refreshAndRender(`Suite ${state.selectedSuiteId} updated.`)
      } catch (error) {
        const msg = `Suite update failed: ${String(error)}`
        appendTelemetry(`[SUITE] ${msg}`)
        alert(msg)
      }
    }
  }

  const editorTemplateBtn = document.getElementById('editorTemplateBtn') as HTMLButtonElement | null
  if (editorTemplateBtn) {
    editorTemplateBtn.onclick = () => {
      state.suiteEditorText = defaultSuiteTemplate()
      renderApp()
      setNotice('Template loaded into suite editor.')
    }
  }

  document.querySelectorAll<HTMLButtonElement>('[data-action="load-suite"]').forEach((button) => {
    button.onclick = () => {
      const id = Number(button.dataset.id)
      state.selectedSuiteId = id
      loadSuiteIntoEditor(id)
      renderApp()
      setNotice(`Suite ${id} loaded into editor.`)
    }
  })

  document.querySelectorAll<HTMLButtonElement>('[data-action="export-suite"]').forEach((button) => {
    button.onclick = () => {
      const id = Number(button.dataset.id)
      const suite = suiteById(id)
      if (!suite) return
      const content = JSON.stringify(
        {
          name: suite.name,
          category: suite.category,
          description: suite.description ?? '',
          tests: suite.tests.map((test) => ({
            order_index: test.order_index,
            name: test.name,
            system_prompt: test.system_prompt ?? '',
            user_prompt: test.user_prompt,
            expected_constraints: test.expected_constraints ?? '',
            tools_schema_json: test.tools_schema_json ?? null,
          })),
        },
        null,
        2,
      )
      downloadText(`${fileSafeName(suite.name)}.json`, content)
      setNotice(`Suite ${suite.name} exported.`)
    }
  })

  document.querySelectorAll<HTMLButtonElement>('[data-action="delete-suite"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      const suite = suiteById(id)
      if (suite?.is_demo) {
        alert('Demo suites are protected. Duplicate and edit instead.')
        return
      }
      if (!confirm(`Delete suite ${id}?`)) return
      await api(`/api/suites/${id}`, { method: 'DELETE' })
      if (state.selectedSuiteId === id) {
        state.selectedSuiteId = 0
        state.suiteEditorText = defaultSuiteTemplate()
      }
      await refreshAndRender(`Suite ${id} deleted.`)
    }
  })

  const raceSuiteSelect = document.getElementById('raceSuiteSelect') as HTMLSelectElement | null
  if (raceSuiteSelect) {
    raceSuiteSelect.onchange = () => {
      state.selectedSuiteId = Number(raceSuiteSelect.value)
    }
  }

  const judgeSelect = document.getElementById('judgeSelect') as HTMLSelectElement | null
  if (judgeSelect) {
    judgeSelect.onchange = () => {
      state.selectedJudgeCarId = Number(judgeSelect.value)
    }
  }

  document.querySelectorAll<HTMLInputElement>('input[data-car-id]').forEach((check) => {
    check.onchange = () => {
      const carId = Number(check.dataset.carId)
      if (check.checked) {
        if (!state.selectedCarIds.includes(carId)) state.selectedCarIds.push(carId)
      } else {
        state.selectedCarIds = state.selectedCarIds.filter((id) => id !== carId)
      }
    }
  })

  const startRaceBtn = document.getElementById('startRaceBtn') as HTMLButtonElement | null
  if (startRaceBtn) {
    startRaceBtn.onclick = async () => {
      if (!state.selectedSuiteId) {
        alert('Select a suite first.')
        return
      }
      if (state.selectedCarIds.length === 0) {
        alert('Select at least one model profile.')
        return
      }

      const precheck = await preflightSelectedCars(state.selectedCarIds)
      if (!precheck.ok) {
        const message = precheck.message ?? 'Connection precheck failed.'
        appendTelemetry(`[PRECHECK] ${message}`)
        setNotice(message)
        alert(message)
        return
      }

      await runCountdown()
      state.telemetryLines = []
      state.hud.clear()
      state.runItemCarMap.clear()

      const result = await api<{ run_id: number }>('/api/runs/start', {
        method: 'POST',
        body: JSON.stringify({
          suite_id: state.selectedSuiteId,
          car_ids: state.selectedCarIds,
          judge_car_id: state.selectedJudgeCarId || null,
        }),
      })

      state.currentRunId = result.run_id
      appendTelemetry(`[RUN ${result.run_id}] started`)
      appendTelemetry(`[RUN CONFIG] suite=${state.selectedSuiteId} profiles=${state.selectedCarIds.map((id) => describeCar(id)).join(' | ')}`)
      setNotice(`RUN ${result.run_id} started`)
      connectRunStream(result.run_id)
      renderApp()
      await refreshData()
    }
  }

  const judgeRunBtn = document.getElementById('judgeRunBtn') as HTMLButtonElement | null
  if (judgeRunBtn) {
    judgeRunBtn.onclick = async () => {
      if (!state.currentRunId) {
        alert('Start or select a run first.')
        return
      }

      appendTelemetry(`[RUN ${state.currentRunId}] judge started`)
      setNotice(`RUN ${state.currentRunId} judge started`)
      await api(`/api/runs/${state.currentRunId}/judge`, {
        method: 'POST',
        body: JSON.stringify({ judge_car_id: state.selectedJudgeCarId || null }),
      })
      appendTelemetry(`[RUN ${state.currentRunId}] judge completed`)
      setNotice(`RUN ${state.currentRunId} judge completed`)
      await refreshAndRender('Judge completed.')
    }
  }

  const toggleScroll = document.getElementById('toggleScrollBtn') as HTMLButtonElement | null
  if (toggleScroll) {
    toggleScroll.onclick = () => {
      state.telemetryPaused = !state.telemetryPaused
      renderApp()
    }
  }

  const clearTelemetryBtn = document.getElementById('clearTelemetryBtn') as HTMLButtonElement | null
  if (clearTelemetryBtn) {
    clearTelemetryBtn.onclick = () => {
      state.telemetryLines = []
      renderApp()
    }
  }

  const historyApply = document.getElementById('historyApply') as HTMLButtonElement | null
  if (historyApply) {
    historyApply.onclick = async () => {
      const status = (document.getElementById('historyStatus') as HTMLSelectElement | null)?.value ?? ''
      const suite = Number((document.getElementById('historySuite') as HTMLSelectElement | null)?.value ?? '0')
      const car = Number((document.getElementById('historyCar') as HTMLSelectElement | null)?.value ?? '0')
      state.historyStatusFilter = (status as RunStatus) || ''
      state.historySuiteFilter = suite
      state.historyCarFilter = car
      await refreshAndRender('History filters applied.')
    }
  }

  const historyReset = document.getElementById('historyReset') as HTMLButtonElement | null
  if (historyReset) {
    historyReset.onclick = async () => {
      state.historyStatusFilter = ''
      state.historySuiteFilter = 0
      state.historyCarFilter = 0
      await refreshAndRender('History filters reset.')
    }
  }

  document.querySelectorAll<HTMLButtonElement>('[data-action="inspect-run"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      const [detail, scorecard] = await Promise.all([
        api<RunDetail>(`/api/runs/${id}`),
        api<{ run_id: number; rows: RunScorecardRow[] }>(`/api/runs/${id}/scorecard`),
      ])
      state.selectedRunDetailId = id
      state.selectedRunDetail = detail
      state.selectedRunScorecard = scorecard.rows
      if (!state.selectedBaselineRunId || state.selectedBaselineRunId === id) {
        const fallback = state.runs.find((run) => run.id !== id)
        state.selectedBaselineRunId = fallback ? fallback.id : 0
      }
      state.selectedRunComparison = []
      renderApp()
      setNotice(`Run ${id} loaded.`)
    }
  })

  document.querySelectorAll<HTMLButtonElement>('[data-action="export-run"]').forEach((button) => {
    button.onclick = async () => {
      const id = Number(button.dataset.id)
      const detail = await api<RunDetail>(`/api/runs/${id}`)
      downloadText(`run-${id}.json`, JSON.stringify(detail, null, 2))
      setNotice(`Run ${id} exported.`)
    }
  })

  const saveSettingsBtn = document.getElementById('saveSettingsBtn') as HTMLButtonElement | null
  if (saveSettingsBtn) {
    saveSettingsBtn.onclick = async () => {
      const items = state.providerSettings.map((setting) => {
        const readNum = (field: string): number => {
          const node = document.querySelector<HTMLInputElement>(
            `input[data-setting="${setting.provider_type}"][data-field="${field}"]`,
          )
          return Number(node?.value ?? 0)
        }
        return {
          provider_type: setting.provider_type,
          max_in_flight: Math.max(1, readNum('max_in_flight')),
          timeout_ms: Math.max(1000, readNum('timeout_ms')),
          retry_count: Math.max(0, readNum('retry_count')),
          retry_backoff_ms: Math.max(0, readNum('retry_backoff_ms')),
        }
      })
      await api<ProviderSetting[]>('/api/settings/providers', {
        method: 'PUT',
        body: JSON.stringify({ items }),
      })
      await refreshAndRender('Provider settings saved.')
    }
  }

  const baselineSelect = document.getElementById('baselineRunSelect') as HTMLSelectElement | null
  if (baselineSelect) {
    baselineSelect.onchange = () => {
      state.selectedBaselineRunId = Number(baselineSelect.value)
    }
  }

  const compareRunBtn = document.getElementById('compareRunBtn') as HTMLButtonElement | null
  if (compareRunBtn) {
    compareRunBtn.onclick = async () => {
      const runId = state.selectedRunDetail?.run.id
      if (!runId) {
        alert('Load a run first.')
        return
      }
      if (!state.selectedBaselineRunId) {
        alert('Select a baseline run.')
        return
      }
      if (state.selectedBaselineRunId === runId) {
        alert('Baseline must be different from the selected run.')
        return
      }
      const compare = await api<{ rows: RunComparisonRow[] }>(
        `/api/runs/${runId}/compare?baseline_run_id=${state.selectedBaselineRunId}`,
      )
      state.selectedRunComparison = compare.rows
      renderApp()
      setNotice(`Compared run ${runId} vs baseline ${state.selectedBaselineRunId}.`)
    }
  }
}

function connectRunStream(runId: number): void {
  if (stream) stream.close()
  stream = new EventSource(buildUrl(`/api/runs/${runId}/stream`))
  let streamErrorLogged = false
  let runEnded = false

  const listen = (eventName: string, handler: (payload: any) => void): void => {
    stream?.addEventListener(eventName, (evt) => {
      const message = evt as MessageEvent
      try {
        const payload = JSON.parse(message.data)
        streamErrorLogged = false
        handler(payload)
      } catch {
        appendTelemetry(`[STREAM] failed to parse ${eventName}`)
      }
    })
  }

  listen('run.started', (p) => appendTelemetry(`[RUN] status=${p.status}`))
  listen('item.started', (p) => {
    const carId = Number(p.car_id)
    state.runItemCarMap.set(Number(p.run_item_id), carId)
    appendTelemetry(`[ITEM ${p.run_item_id}] started profile=${describeCar(carId)} test=${p.test_id}`)
  })
  listen('request.sent', (p) => appendTelemetry(`[ITEM ${p.run_item_id}] request sent model=${p.model} loop=${p.loop}`))
  listen('ttft.recorded', (p) => appendTelemetry(`[ITEM ${p.run_item_id}] TTFT ${p.ttft_ms}ms`))
  listen('token.delta', (p) => appendTelemetry(`[ITEM ${p.run_item_id}] ${p.token}`))
  listen('tool.call.detected', (p) => appendTelemetry(`[TOOLS] detected ${p.count} calls`))
  listen('tool.call.executed', (p) => appendTelemetry(`[TOOL] ${p.tool_name} -> ${JSON.stringify(p.result)}`))
  listen('tool.loop.continue', (p) => appendTelemetry(`[ITEM ${p.run_item_id}] tool loop continue (${p.tool_calls})`))
  listen('tool.loop.exhausted', (p) =>
    appendTelemetry(`[ITEM ${p.run_item_id}] tool loop reached max iterations (${p.limit}); marked partial`),
  )
  listen('item.error', (p) => {
    appendTelemetry(`[ITEM ${p.run_item_id}] error: ${p.error}`)
    if (String(p.error).includes('All connection attempts failed')) {
      const carId = state.runItemCarMap.get(Number(p.run_item_id))
      if (carId) {
        appendTelemetry(`[HINT] Check selected profile endpoint: ${describeCar(carId)}`)
      }
    }
  })
  listen('item.metrics', (p) => {
    state.hud.set(Number(p.run_item_id), {
      ttft_ms: p.ttft_ms,
      latency_ms: p.latency_ms,
      tokens_per_sec: p.tokens_per_sec,
      output_tokens: p.output_tokens,
      estimated: p.estimated,
    })
    appendTelemetry(`[ITEM ${p.run_item_id}] latency=${p.latency_ms}ms tps=${p.tokens_per_sec ?? '-'} tokens=${p.output_tokens}`)
    renderApp()
  })
  listen('item.assertions', (p) => appendTelemetry(`[ITEM ${p.run_item_id}] checks ${p.passed}/${p.total}`))
  listen('item.completed', (p) => appendTelemetry(`[ITEM ${p.run_item_id}] completed status=${p.status}`))
  listen('run.completed', async (p) => {
    runEnded = true
    appendTelemetry(`[RUN ${runId}] completed status=${p.status}`)
    if (stream) {
      stream.close()
      stream = null
    }
    await refreshAndRender('Run completed.')
  })
  listen('judge.started', () => appendTelemetry('[JUDGE] started'))
  listen('judge.completed', async (p) => {
    appendTelemetry(`[JUDGE] completed items=${p.item_scores}`)
    await refreshAndRender('Judge update received.')
  })

  stream.onerror = () => {
    if (runEnded) return
    if (!streamErrorLogged) {
      appendTelemetry('[STREAM] disconnected')
      streamErrorLogged = true
    }
  }
}

async function refreshAndRender(message?: string): Promise<void> {
  await refreshData()
  renderApp()
  if (message) {
    appendTelemetry(`[INFO] ${message}`)
    setNotice(message)
  }
}

async function bootstrap(): Promise<void> {
  await refreshData()
  state.selectedCarIds = []
  if (!state.suiteEditorText) {
    state.suiteEditorText = defaultSuiteTemplate()
  }
  renderApp()
}

bootstrap().catch((error) => {
  app.innerHTML = `<div class="card">Startup failed: ${String(error)}</div>`
})
