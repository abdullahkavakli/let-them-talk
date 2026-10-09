import { test, expect, mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'
import { cleanSuggestion, modelFor, report } from './register'

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

const ON = 'Ultracode on (this session only): dynamic workflows on every task. Effort stays xhigh.'

const BACKGROUND = { CLAUDE_CODE_SESSION_KIND: 'bg' } // how Claude Code starts a background agent

/** A chat whose /effort runs are recorded; by default a background agent.
 * A plugin's /effort status waits until the chat is idle: idle() lets it run. */
function chat(on: On, env: Record<string, string> = BACKGROUND) {
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, env)
  const ran: string[] = []
  let idle: () => void = () => {}
  const quiet = new Promise<void>(resolve => { idle = () => resolve() })
  on('command.run', async ($, e) => {
    ran.push(e.args)
    if (e.origin.kind === 'plugin') await quiet
    return {}
  })
  return { clock, ran, idle }
}

/** /effort typed in the chat, as Claude Code runs it. */
const effort = ($: Engine, args: string) => $.command.run({
  command: 'effort', args, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 },
})

let rows = 0
/** The rows Claude Code appends for a command run while the chat is idle: its
 * name, then its answer (a subagent's carry its agentId). */
async function answer($: Engine, args: string, said: string, command = 'effort', agentId?: string) {
  for (const text of [
    `<command-name>/${command}</command-name>\n            <command-message>${command}</command-message>\n            <command-args>${args}</command-args>`,
    `<local-command-stdout>${said}</local-command-stdout>`,
  ]) {
    await $.session.append({
      door: 'command', origin: { kind: 'composer' }, uuid: `row-${++rows}`, ...(agentId ? { agentId } : {}),
      message: { type: 'user', role: 'user', content: [{ type: 'text', text }] },
    })
  }
}

test('an /effort answered at once (the agent was idle) needs no /effort status', async ($, on) => {
  const { clock, ran } = chat(on)
  await effort($, 'ultracode on')
  await answer($, 'ultracode on', ON)
  await effort($, 'ultracode on') // refused: answered all the same
  await answer($, 'ultracode on', "Ultracode isn't available on claude-sonnet-4-5. Valid options are: low, medium, high, xhigh, max, auto")
  await effort($, '')
  await answer($, '', 'Cancelled') // the panel closed with Esc
  await clock.advance(5000)
  expect(ran).toEqual(['ultracode on', 'ultracode on', ''])
})

test('a switch while a background agent works is followed by /effort status, run once it is idle', async ($, on) => {
  const { clock, ran, idle } = chat(on)
  await effort($, 'ultracode on') // while it works: Claude Code appends no answer
  await clock.advance(1000)
  expect(ran).toEqual(['ultracode on'])
  await clock.advance(1000)
  expect(ran).toEqual(['ultracode on', 'status'])
  idle()
  await answer($, 'status', 'Current effort level: xhigh (Deeper reasoning than high) · Ultracode on')
  await clock.advance(5000)
  expect(ran).toEqual(['ultracode on', 'status']) // its own answer starts nothing more
})

test('its panel opened while the agent works is followed by one /effort status; a level by none', async ($, on) => {
  const { clock, ran } = chat(on)
  await effort($, 'high') // a level leaves ultracode as it is
  await clock.advance(2000)
  expect(ran).toEqual(['high'])
  await effort($, '') // the panel, where Tab switches it unseen
  await clock.advance(1000)
  await effort($, 'ultracode off') // only one /effort status for both
  await clock.advance(2000)
  expect(ran).toEqual(['high', '', 'ultracode off', 'status'])
})

for (const [chatKind, env] of [['terminal or IDE', {}], ['named interactive', { CLAUDE_CODE_SESSION_KIND: 'interactive' }]] as const) {
  test(`an ordinary chat (${chatKind}) gets no /effort status`, async ($, on) => {
    const { clock, ran } = chat(on, env)
    await effort($, 'ultracode on') // while it works
    await effort($, '')
    await clock.advance(5000)
    expect(ran).toEqual(['ultracode on', ''])
  })
}

test('another command\'s answer is not the answer to an /effort', async ($, on) => {
  const { clock, ran } = chat(on)
  await effort($, 'ultracode on') // while it works
  await answer($, '', 'Total cost: $0.12', 'cost')
  await clock.advance(2000)
  expect(ran).toEqual(['ultracode on', 'status'])
})

test('a subagent\'s /effort answer is not the agent\'s', async ($, on) => {
  const { clock, ran } = chat(on)
  await effort($, 'ultracode on') // while it works
  await answer($, 'ultracode on', ON, 'effort', 'agent-1')
  await clock.advance(2000)
  expect(ran).toEqual(['ultracode on', 'status'])
})
