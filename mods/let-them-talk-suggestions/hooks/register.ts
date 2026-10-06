import type { Register } from 'claude-code'

// Let Them Talk (this repo) shows each chat's suggested next prompt in its
// Send box: the same one this chat's prompt box shows.
//
// - When Claude Code makes its own suggestion (only while this chat's window
//   is focused), it is passed on as it is shown.
// - When it doesn't (the window is in the background, or a background agent
//   has none) and Let Them Talk has this chat open, one is made the way
//   Claude Code makes its own: one tool-less reply of this chat's model over
//   its own conversation, while that is still cached. It goes both to the app
//   and into this chat's prompt box, so the two show the same text.

const APP = 'http://localhost:8765' // Let Them Talk's default port (LTT_PORT)
const HEADERS = { 'Content-Type': 'application/json', 'X-Let-Them-Talk': '1' }
const TICK_MS = 2000
const OWN_WAIT_MS = 8000 // Claude Code makes its own within a few seconds of the turn's end
const WINDOW_MS = 300_000 // after that the conversation may no longer be cached (server: MOD_WINDOW)
const HELLO_EVERY_MS = 300_000 // so the app keeps counting this chat as having the mod

const PROMPT = `[Suggestion only. Do not answer this message or continue the task.]
Predict what the user will most likely type next in this chat. Predict what they
would type, not what they should do: they should think "I was about to type that".
If you just asked whether to go on, answer like "yes" or "go ahead"; if you offered
options, pick the one this user would; if a task is done and the next step is
obvious, name it, like "commit it" or "run the tests"; after an error or a
misunderstanding, suggest nothing. Be specific. Never suggest thanks or praise, a
question, your own voice ("Let me..."), or anything new the user didn't ask for.
One sentence of 2 to 12 words, in the user's language and style. If the next step
isn't obvious, reply with a single hyphen. Reply with only the suggestion.`

const SILENT = /^\W*(-|none|nothing|silence|no suggestion.*|nothing to suggest.*|done)\W*$|^[[(].*[\])]$/i

export function cleanSuggestion(text: string): string | undefined {
  const line = text.trim().split('\n')[0].trim().replace(/^["'“”]+|["'“”]+$/g, '').trim()
  return line && !SILENT.test(line) && line.split(/\s+/).length <= 12 ? line : undefined
}

export const register: Register = on => {
  let turn = 0 // main-loop turns ended so far
  let starts = 0 // main-loop turns started so far
  let ownFor = -1 // the turn Claude Code's own suggestion came after
  let pending: { turn: number; starts: number; waited: number } | undefined // a turn still without one
  let busy = false
  let helloFor: string | undefined
  let sinceHello = 0

  // Work after a turn outlives the turn's own hooks, so a timer started here does it.
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    // A headless run (claude -p, such as the app's own TL;DR runs) has no prompt box.
    if (!e.isInteractive) return started
    $.clock.every(TICK_MS, () => {
      if (busy) return
      busy = true
      void (async () => {
        try {
          // Read each time: /clear and /resume carry on under another id.
          const sessionId = await $.session.id()
          sinceHello += TICK_MS
          if (sessionId !== helloFor || sinceHello >= HELLO_EVERY_MS) {
            await $.http.fetch(`${APP}/api/suggestion/hello`, {
              method: 'POST', headers: HEADERS,
              body: JSON.stringify({ sessionId, surface: e.surface }),
            })
            helloFor = sessionId
            sinceHello = 0
          }
          if (!pending) return
          pending.waited += TICK_MS
          const { turn: forTurn, starts: forStarts, waited } = pending
          if (ownFor === forTurn || waited > WINDOW_MS) { // Claude Code made its own, or too late
            pending = undefined
            return
          }
          if (waited < OWN_WAIT_MS) return
          const wanted = await $.http.fetch(`${APP}/api/suggestion/wanted?session=${sessionId}`)
          if (!wanted.ok || JSON.parse(wanted.text).wanted !== true) return // ask again next tick
          pending = undefined
          const reply = await $.model.fork({ prompt: PROMPT })
          const text = reply.isAnswered ? cleanSuggestion(reply.text) : undefined
          if (ownFor === forTurn || forTurn !== turn || forStarts !== starts) return // a newer turn
          if (text) await $.prompt.suggest({ text })
          // made "none" tells the app this turn has nothing, so it stops waiting for one
          await $.http.fetch(`${APP}/api/suggestion`, {
            method: 'POST', headers: HEADERS,
            body: JSON.stringify({ sessionId, text: text ?? '', made: text ? 'fork' : 'none' }),
          })
        } catch {
          // Let Them Talk isn't running, or the fork failed: nothing to show.
        } finally {
          busy = false
        }
      })()
    })
    return started
  })

  on('prompt.suggest', async ($, e, next) => {
    const shown = await next(e)
    // Claude Code's own guess; one this mod (a plugin) proposed is already sent.
    if (e.origin?.kind === 'plugin' || !e.text.trim()) return shown
    ownFor = turn
    try {
      const sessionId = await $.session.id()
      await $.http.fetch(`${APP}/api/suggestion`, {
        method: 'POST', headers: HEADERS, body: JSON.stringify({ sessionId, text: e.text, made: 'claude' }),
      })
    } catch {
      // Let Them Talk isn't running: the suggestion shows here all the same.
    }
    return shown
  })

  on('turn.start', async ($, e, next) => {
    starts++
    pending = undefined // the user moved on: a suggestion for the last turn is moot
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    // The main loop's answers only: not subagents, interrupts or errors.
    if (!e.agentId && !e.isAborted && e.reason === 'answer') pending = { turn: ++turn, starts, waited: 0 }
    return done
  })
}
