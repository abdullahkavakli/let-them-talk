import { test, expect, mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'
import { cleanSuggestion, modelFor, processOf, report, ultracodeSaid } from './register'

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

// ---------------------------------------------------------------- ultracode

const SID = '0c0c0c0c-0000-4000-8000-00000000000c'
// /proc/<pid>/stat as Linux writes it: field 22, the start time, is the 20th after the name
const STAT = '4242 (2.1.295) S 1 4242 4242 0 -1 4194304 478 0 0 0 10 3 0 0 20 0 12 0 98765 1024 64'
const ON = 'Ultracode on (this session only): dynamic workflows on every task. Effort stays xhigh.'
const OK = { status: 200, ok: true, headers: {}, text: '{}' }

/** A chat whose /effort runs and the app's answers are recorded: what the
 * mod told the app (ultracode only), and each /effort Claude Code ran. A
 * plugin's /effort status waits until the chat is idle: idle() lets it run. */
function chat(on: On, app: { down?: boolean } = {}) {
  const clock = mock.clock(on, { now: 1_000_000 })
  const told: unknown[] = []
  const ran: string[] = []
  let idle: () => void = () => {}
  const quiet = new Promise<void>(resolve => { idle = () => resolve() })
  on('session.id', () => ({ value: SID }))
  on('fs.read', () => ({ value: STAT }))
  on('http.fetch', ($, e) => {
    if (!e.url.endsWith('/api/mod/ultracode')) return { value: OK }
    if (app.down) throw new Error('connection refused')
    told.push(JSON.parse(e.init?.body ?? '{}'))
    return { value: OK }
  })
  on('command.run', async ($, e) => {
    ran.push(e.args)
    if (e.origin.kind === 'plugin') await quiet
    return {}
  })
  return { clock, told, ran, idle }
}

/** /effort typed in the chat, as Claude Code runs it. */
const effort = ($: Engine, args: string) => $.command.run({
  command: 'effort', args, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 },
})

let rows = 0
/** The rows Claude Code appends for a command run while the chat is idle: its name, then its answer. */
async function answer($: Engine, args: string, said: string) {
  for (const text of [
    `<command-name>/effort</command-name>\n            <command-message>effort</command-message>\n            <command-args>${args}</command-args>`,
    `<local-command-stdout>${said}</local-command-stdout>`,
  ]) {
    await $.session.append({
      door: 'command', origin: { kind: 'composer' }, uuid: `row-${++rows}`,
      message: { type: 'user', role: 'user', content: [{ type: 'text', text }] },
    })
  }
}

test('reads what an /effort answer says of ultracode', () => {
  expect(ultracodeSaid(ON)).toBe(true)
  expect(ultracodeSaid('Ultracode off. Effort stays xhigh.')).toBe(false)
  expect(ultracodeSaid('Current effort level: xhigh (Deeper reasoning than high) · Ultracode on')).toBe(true)
  expect(ultracodeSaid('Current effort level: xhigh (Deeper reasoning than high)')).toBe(false)
  expect(ultracodeSaid('Effort level: auto (currently high)')).toBe(false)
  // nothing of it: a refusal, a level, the panel closed with Esc, a typo
  expect(ultracodeSaid("Ultracode isn't available on claude-sonnet-4-5. Valid options are: low, medium, high, xhigh, max, auto")).toBe(undefined)
  expect(ultracodeSaid('Ultracode needs dynamic workflows enabled (see /config). Valid options are: low, high, auto')).toBe(undefined)
  expect(ultracodeSaid('Set effort level to max (this session only): Maximum capability')).toBe(undefined)
  expect(ultracodeSaid('Cancelled')).toBe(undefined)
  expect(ultracodeSaid('Invalid argument: ultracode maybe. Valid options are: low, auto, ultracode [on|off]')).toBe(undefined)
})

test('knows its process as the app finds it', () => {
  expect(processOf(STAT)).toEqual({ pid: 4242, procStart: '98765' })
  expect(processOf('9 (a) b) c) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 777 1')).toEqual({ pid: 9, procStart: '777' })
  expect(processOf('')).toEqual({})
})

test('tells the app a switch Claude Code answered, with its process', async ($, on) => {
  const { clock, told, ran } = chat(on)
  await effort($, 'ultracode on')
  await answer($, 'ultracode on', ON)
  await clock.advance(2000)
  expect(told).toEqual([{ sessionId: SID, on: true, at: expect.any(Number), pid: 4242, procStart: '98765' }])
  expect(ran).toEqual(['ultracode on']) // answered: no /effort status
  await effort($, 'ultracode off')
  await answer($, 'ultracode off', 'Ultracode off. Effort stays xhigh.')
  await clock.advance(2000)
  expect(told).toHaveLength(2)
  expect(told[1]).toMatchObject({ on: false })
})

test('tells nothing for a refused switch, a level, or a panel closed with Esc', async ($, on) => {
  const { clock, told, ran } = chat(on)
  await effort($, 'ultracode on')
  await answer($, 'ultracode on', "Ultracode isn't available on claude-sonnet-4-5. Valid options are: low, medium, high, xhigh, max, auto")
  await effort($, 'max')
  await answer($, 'max', 'Set effort level to max (this session only): Maximum capability')
  await effort($, '')
  await answer($, '', 'Cancelled')
  await clock.advance(5000)
  expect(told).toEqual([])
  expect(ran).toEqual(['ultracode on', 'max', ''])
})

test('a switch while the chat works is told from /effort status once it is idle', async ($, on) => {
  const { clock, told, ran, idle } = chat(on)
  await effort($, 'ultracode on') // while it works: Claude Code appends no answer
  await clock.advance(1000)
  expect(ran).toEqual(['ultracode on'])
  await clock.advance(1000)
  expect(ran).toEqual(['ultracode on', 'status'])
  expect(told).toEqual([]) // the words typed aren't the answer: it may have been refused
  idle()
  await answer($, 'status', 'Current effort level: xhigh (Deeper reasoning than high) · Ultracode on')
  await clock.advance(0)
  expect(told).toEqual([expect.objectContaining({ on: true })])
})

test('its panel opened while the chat works is read once it is idle; a level changes nothing', async ($, on) => {
  const { clock, told, ran, idle } = chat(on)
  await effort($, 'high') // a level leaves ultracode as it is
  await clock.advance(2000)
  expect(ran).toEqual(['high'])
  await effort($, '') // the panel, where Tab switches it unseen
  await clock.advance(1000)
  await effort($, 'ultracode off') // only one /effort status for both
  await clock.advance(2000)
  expect(ran).toEqual(['high', '', 'ultracode off', 'status'])
  idle()
  await answer($, 'status', 'Current effort level: xhigh (Deeper reasoning than high)')
  await clock.advance(0)
  expect(told).toEqual([expect.objectContaining({ on: false })])
})

test('a report the app missed is sent again once it is up', async ($, on) => {
  const app = { down: true }
  const { clock, told } = chat(on, app)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  await effort($, 'ultracode on')
  await answer($, 'ultracode on', ON)
  await clock.advance(2100)
  expect(told).toEqual([])
  app.down = false
  await clock.advance(2000)
  expect(told).toEqual([expect.objectContaining({ on: true })])
  await clock.advance(4000)
  expect(told).toHaveLength(1)
})
