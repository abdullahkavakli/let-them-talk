import { test, expect } from 'claude-code/testing'
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
