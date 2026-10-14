import { test, expect, mock } from 'claude-code/testing'
import { cleanSuggestion, modelFor, report, START, startReport, UV_LINK } from './register'

// Sending needs the chat's id ($.session.id) and making one needs its
// conversation ($.model.fork), which only a real session has; those paths
// are checked live. These cover what the mod must never break.

test('still shows the suggestion when Let Them Talk is not running', async ($, on) => {
  on('http.fetch', () => { throw new Error('connection refused') })
  on('prompt.suggest', () => ({ isShown: true }))

  expect((await $.prompt.suggest({ text: 'run the tests' })).isShown).toBe(true)
})

test('sends nothing for a blank suggestion', async ($, on) => {
  let calls = 0
  on('http.fetch', () => { calls++; return { status: 200, ok: true, headers: {}, text: '' } })
  on('prompt.suggest', () => ({ isShown: false }))

  await $.prompt.suggest({ text: '   ' })
  expect(calls).toBe(0)
})

test('keeps a made suggestion only when it reads like one', () => {
  expect(cleanSuggestion('  "commit it"  ')).toBe('commit it')
  expect(cleanSuggestion('yes, go ahead\nand then push')).toBe('yes, go ahead')
  expect(cleanSuggestion('-')).toBe(undefined)
  expect(cleanSuggestion('Nothing to suggest.')).toBe(undefined)
  expect(cleanSuggestion('(silence)')).toBe(undefined)
  expect(cleanSuggestion('one two three four five six seven eight nine ten eleven twelve thirteen')).toBe(undefined)
})

test('reports a suggestion only when the box shows it', () => {
  expect(report('commit it', true, 'claude')).toEqual({ text: 'commit it', made: 'claude' })
  expect(report('commit it', false, 'claude')).toEqual({ text: '', made: 'none' })
  expect(report('yes', true, 'fork')).toEqual({ text: 'yes', made: 'fork' })
  expect(report(undefined, true, 'fork')).toEqual({ text: '', made: 'none' })
  expect(report('   ', true, 'claude')).toEqual({ text: '', made: 'none' })
})

test('runs on the app\'s model until the chat picks another', () => {
  expect(modelFor(undefined, undefined, 'claude-opus-5-5')).toEqual({ model: 'claude-opus-5-5', startedOn: undefined, dropped: false })
  const first = modelFor('claude-sonnet-5-5', undefined, 'claude-opus-5-5')
  expect(first).toEqual({ model: 'claude-sonnet-5-5', startedOn: 'claude-opus-5-5', dropped: false })
  expect(modelFor('claude-sonnet-5-5', first.startedOn, 'claude-opus-5-5').model).toBe('claude-sonnet-5-5')
  expect(modelFor('claude-sonnet-5-5', first.startedOn, 'claude-haiku-4-5')).toEqual({ model: 'claude-haiku-4-5', startedOn: 'claude-opus-5-5', dropped: true })
  // the same model in the chat's own spelling stays as it is
  expect(modelFor('claude-opus-5-5', undefined, 'claude-opus-5-5[1m]').model).toBe('claude-opus-5-5[1m]')
})

test('runs no command of its own: an /effort, even in a background agent, is followed by nothing', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { CLAUDE_CODE_SESSION_KIND: 'bg' }) // how Claude Code starts a background agent
  const ran: string[] = []
  on('command.run', async (_$, e) => { ran.push(`${e.command} ${e.args}`.trim()); return {} })

  for (const args of ['ultracode on', '', 'high']) {
    await $.command.run({
      command: 'effort', args, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 },
    })
  }
  await clock.advance(10_000)
  expect(ran).toEqual(['effort ultracode on', 'effort', 'effort high'])
})

// /let-them-talk. What START itself does (a session of its own, no chat
// variables, what it prints) is checked with real processes in
// tests/check_server.py; here, how the command runs it and what it says.

const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
const page = (server: string) => ({ value: { status: 200, ok: true, headers: { server }, text: '<!doctype html>' } })
const typed = { args: '', origin: { kind: 'composer' as const }, presentation: { isFullscreen: false, columns: 120 } }

test('/let-them-talk is there in every chat, headless ones too', async ($, on) => {
  const registered: string[] = []
  on('command.register', (_$, e) => { registered.push(e.name); return { value: { command: e.name } } })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/tmp', surface: null, isInteractive: false })
  expect(registered).toEqual(['let-them-talk'])
})

test('/let-them-talk starts the app with uvx, apart from the chat, on the port the app uses', async ($, on) => {
  const runs: (readonly string[])[] = []
  mock.env(on, { LTT_PORT: '9999' })
  on('http.fetch', () => ({ deny: 'connection refused' }))
  on('process.run', (_$, e) => { runs.push(e.argv); return ran('running\nInstalled 1 package in 12ms\nLet Them Talk running at http://localhost:9999  (Ctrl+C to stop)\n') })

  const { text } = await $.command.run({ command: 'let-them-talk', ...typed })
  expect(runs).toEqual([['sh', '-c', START, 'let-them-talk', 'http://localhost:9999']])
  expect(text).toBe('Let Them Talk is running at http://localhost:9999 and opens in your browser. It keeps running after this chat ends.')
})

test('/let-them-talk when the app runs already: the app opens its page', async ($, on) => {
  let runs = 0
  mock.env(on, {})
  on('http.fetch', (_$, e) => { expect(e.url).toBe('http://localhost:8765/'); return page('LetThemTalk/1 Python/3.12.3') })
  on('process.run', () => { runs++; return ran('ended 0\nLet Them Talk is already running at http://localhost:8765\n') })

  const { text } = await $.command.run({ command: 'let-them-talk', ...typed })
  expect(runs).toBe(1) // uvx let-them-talk opens the page, as when typed in a terminal
  expect(text).toBe('Let Them Talk is already running. Opening http://localhost:8765 in your browser.')
})

test('/let-them-talk without uv says so, with where to get it', async ($, on) => {
  mock.env(on, {})
  on('http.fetch', () => page('nginx'))
  on('process.run', () => ran('no-uv\n'))

  const done = await $.command.run({ command: 'let-them-talk', ...typed })
  expect(done.text).toBe(`Let Them Talk starts with uv, which isn't installed. Install uv (${UV_LINK}), then run /let-them-talk again.`)
  expect(done.exitCode).toBe(1)
})

test('/let-them-talk says why the app did not start, or that it is still starting', () => {
  const url = 'http://localhost:8765'
  const taken = 'Port 8765 is already used by another program, not Let Them Talk. Stop that program, or use another port: LTT_PORT=8766 let-them-talk'
  expect(startReport(`ended 1\n${taken}\n`, url, false)).toEqual({ text: `Let Them Talk didn't start.\n\n${taken}`, exitCode: 1 })
  expect(startReport('', url, false)).toEqual({ text: "Let Them Talk didn't start.", exitCode: 1 })
  // the first start downloads it: nothing printed yet
  expect(startReport('running\n', url, false).text).toBe('Let Them Talk is starting. The first start downloads it, which can take a minute; '
    + 'then it opens in your browser at http://localhost:8765. It keeps running after this chat ends.')
  // running already, but uvx could not open it (offline, say)
  expect(startReport('ended 2\nerror: Failed to fetch\n', url, true).text).toBe('Let Them Talk is already running. Open http://localhost:8765 in your browser.')
})
