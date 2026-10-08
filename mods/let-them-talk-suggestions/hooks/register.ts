import type { EngineInterface, Register } from 'claude-code'

// Let Them Talk (this repo) shows each chat's suggested next prompt in its
// Send box: exactly what this chat's own prompt box shows, or nothing.
//
// - When Claude Code shows its own suggestion, it is passed on.
// - When it made none (the terminal is unfocused, or a background agent has
//   nobody attached) and Let Them Talk has this chat open, one is made the
//   way Claude Code makes its own ($.model.fork over the cached conversation)
//   and shown in this chat's prompt box too, so both match.
// - A background agent that ends its turn waiting on you is left alone:
//   Claude Code makes that one itself and saves it, and the app reads it there.
// Only text the box really shows is reported; otherwise "none".
//
// It also runs a chat on the model picked in the app's New agent, for a Chat in
// IDE: the editor link that opens one can't name a model, so the app says
// which when the chat's first turns start, and this names it on the chat's
// own requests (not its subagents'). A model you then pick in the chat wins.
//
// And it tells the app when ultracode is on or off in this chat, as Claude
// Code answers an /effort: "Ultracode on …", "Ultracode off …", or for
// /effort status a line that names ultracode only while it is on. A refused
// switch (a model without it, workflows off), an effort level alone and a
// panel closed with Esc ("Cancelled") say nothing, so nothing is reported.
// An /effort run while the chat works (typed, or Tab in its Effort panel)
// answers on its screen only, which no hook sees: once the chat is idle,
// this runs /effort status (a line the chat shows) and reports that answer.

const APP = 'http://localhost:8765' // Let Them Talk's default port (LTT_PORT)
const HEADERS = { 'Content-Type': 'application/json', 'X-Let-Them-Talk': '1' }
const TICK_MS = 2000
const OWN_WAIT_MS = 12000 // Claude Code makes its own within a few seconds of the turn's end
const WINDOW_MS = 300_000 // after that the conversation may no longer be cached (server: MOD_WINDOW)
const HELLO_EVERY_MS = 300_000 // so the app keeps counting this chat as having the mod
const MODEL_ASKS = 3 // turns at a chat's start the app is asked for a model (it knows by the first)
const ANSWER_WAIT_MS = 1500 // an idle /effort's answer is appended within ms; a busy one's never
const COMMAND_NAME = /<command-name>\/?([^<]*)<\/command-name>/
const COMMAND_OUT = /^\s*<local-command-stdout>([\s\S]*?)<\/local-command-stdout>/
const MAY_SWITCH = /^\s*(ultracode(\s|$)|$)/i // /effort ultracode [on|off], or its panel (no words): Claude Code's own reading

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

/** What to tell the app about a suggestion: the text only if the box shows it. */
export function report(text: string | undefined, isShown: boolean, made: 'claude' | 'fork') {
  return text?.trim() && isShown ? { text, made } : { text: '', made: 'none' as const }
}

export function cleanSuggestion(text: string): string | undefined {
  const line = text.trim().split('\n')[0].trim().replace(/^["'“”]+|["'“”]+$/g, '').trim()
  return line && !SILENT.test(line) && line.split(/\s+/).length <= 12 ? line : undefined
}

/** The model a request of this chat names: the app's pick (a full id), until
 * the chat's own model changes under it (you picked another in the chat), then
 * the chat's. The chat's own spelling of the same model ([1m]) is kept. */
export function modelFor(wanted: string | undefined, startedOn: string | undefined, now: string) {
  if (!wanted) return { model: now, startedOn, dropped: false }
  if (startedOn !== undefined && now !== startedOn) return { model: now, startedOn, dropped: true }
  return { model: now.startsWith(wanted) ? now : wanted, startedOn: startedOn ?? now, dropped: false }
}

/** What Claude Code's answer to an /effort says of ultracode: true (on), false
 * (off), or undefined when it says nothing of it (a level, "Cancelled", a
 * refused switch). /effort status names it only while it is on. */
export function ultracodeSaid(answer: string): boolean | undefined {
  const said = /\bUltracode (on|off)\b/.exec(answer)
  if (said) return said[1] === 'on'
  return /^\s*(Current effort level: |Effort level: auto\b)/.test(answer) ? false : undefined
}

/** This chat's process as the app finds it: its pid and start time (field 22
 * of /proc/<pid>/stat), or nothing where there is no /proc. */
export function processOf(stat: string): { pid?: number; procStart?: string } {
  const pid = Number.parseInt(stat, 10)
  const procStart = stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19]
  return Number.isInteger(pid) && pid > 0 && procStart && /^\d+$/.test(procStart) ? { pid, procStart } : {}
}

/** What the mod keeps to tell the app about ultracode. */
type Ultra = {
  lastCommand?: string // the command whose answer is appended next
  efforts: number // /effort runs so far
  answered: number // the last /effort run whose answer was appended
  looking: boolean // this mod's /effort status waits for the chat to be idle
  proc?: { pid?: number; procStart?: string } // this chat's process
  unsent?: string // a report the app didn't take (it was down), sent again next tick
}

/** Sends one report. The app keeps the newest it gets, so an old one sent late changes nothing. */
async function sendUltracode($: EngineInterface, ultra: Ultra, body: string) {
  try {
    const sent = await $.http.fetch(`${APP}/api/mod/ultracode`, { method: 'POST', headers: HEADERS, body })
    if (sent.status >= 500) ultra.unsent = body
    else if (ultra.unsent === body) ultra.unsent = undefined
  } catch {
    ultra.unsent = body // Let Them Talk isn't running: it hears once it is
  }
}

async function tellUltracode($: EngineInterface, ultra: Ultra, isOn: boolean) {
  try {
    ultra.proc ??= processOf(String(await $.fs.read('/proc/self/stat').catch(() => '')))
    const at = await $.clock.now()
    await sendUltracode($, ultra, JSON.stringify({ sessionId: await $.session.id(), on: isOn, at, ...ultra.proc }))
  } catch {
    // no session id yet: nothing to report it for
  }
}

export const register: Register = on => {
  let turn = 0 // main-loop turns ended so far
  let starts = 0 // main-loop turns started so far
  let ownFor = -1 // the turn Claude Code's own suggestion came after
  let pending: { turn: number; starts: number; waited: number } | undefined // a turn still without one
  let busy = false
  let helloFor: string | undefined
  let sinceHello = 0
  let unsent: string | undefined // a report the app didn't take (it was down), sent again next tick
  let wanted: string | undefined // the model the app picked for this chat
  let startedOn: string | undefined // the chat's own model when that took over
  let asked = 0
  const ultra: Ultra = { efforts: 0, answered: 0, looking: false }

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
              method: 'POST', headers: HEADERS, body: JSON.stringify({ sessionId }),
            })
            helloFor = sessionId
            sinceHello = 0
          }
          if (ultra.unsent) await sendUltracode($, ultra, ultra.unsent)
          if (unsent) {
            const sent = await $.http.fetch(`${APP}/api/suggestion`, { method: 'POST', headers: HEADERS, body: unsent })
            if (sent.ok) unsent = undefined
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
          const shown = text ? await $.prompt.suggest({ text }) : undefined
          // "none" tells the app this turn has nothing, so it stops waiting for one
          const body = JSON.stringify({ sessionId, ...report(text, shown?.isShown === true, 'fork') })
          const sent = await $.http.fetch(`${APP}/api/suggestion`, { method: 'POST', headers: HEADERS, body })
          if (!sent.ok) unsent = body
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
    let body: string | undefined
    try {
      const sessionId = await $.session.id()
      body = JSON.stringify({ sessionId, ...report(e.text, shown.isShown, 'claude') })
      const sent = await $.http.fetch(`${APP}/api/suggestion`, { method: 'POST', headers: HEADERS, body })
      if (!sent.ok) unsent = body
    } catch {
      unsent = body // Let Them Talk isn't running: the suggestion shows here all the same
    }
    return shown
  })

  on('turn.start', async ($, e, next) => {
    starts++
    pending = undefined // the user moved on: a suggestion for the last turn is moot
    if (!wanted && asked < MODEL_ASKS) {
      asked++
      try {
        const reply = await $.http.fetch(`${APP}/api/mod/model?session=${await $.session.id()}`)
        if (reply.ok) wanted = JSON.parse(reply.text).model || undefined
      } catch {
        // Let Them Talk isn't running: the chat's own model
      }
    }
    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    if (e.agentId || !wanted) return yield* next(e)
    const pick = modelFor(wanted, startedOn, e.model)
    startedOn = pick.startedOn
    if (pick.dropped) wanted = undefined
    return yield* next(pick.model === e.model ? e : { ...e, model: pick.model })
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    // The main loop's answers only: not subagents, interrupts or errors.
    if (!e.agentId && !e.isAborted && e.reason === 'answer') pending = { turn: ++turn, starts, waited: 0 }
    return done
  })

  // An /effort run: while the chat is idle its answer is appended at once
  // (below); while it works, never. Then, for one that may have switched
  // ultracode, /effort status, which Claude Code queues until it is idle.
  on('command.run', { command: 'effort' }, async ($, e, next) => {
    const run = ++ultra.efforts
    const ran = await next(e)
    $.clock.after(ANSWER_WAIT_MS, () => {
      if (ultra.answered >= run || ultra.looking || !MAY_SWITCH.test(e.args)) return
      ultra.looking = true
      $.command.run({ command: 'effort', args: 'status' })
        .catch(() => undefined) // the chat ended: its next prompt tells the app
        .finally(() => { ultra.looking = false })
    })
    return ran
  }).catch(($, e, next) => next(e))

  // The rows an /effort leaves in the conversation: its name, then its answer.
  on('session.append', { door: 'command' }, async ($, e, next) => {
    const kept = await next(e)
    if (e.agentId) return kept
    const text = e.message.content.map(block => (block.type === 'text' ? block.text : '')).join('')
    const name = COMMAND_NAME.exec(text)
    const out = name ? null : COMMAND_OUT.exec(text)
    if (name) ultra.lastCommand = name[1]?.trim()
    else if (out) {
      if (ultra.lastCommand === 'effort') {
        ultra.answered = ultra.efforts
        const isOn = ultracodeSaid(out[1] ?? '')
        if (isOn !== undefined) $.clock.after(0, () => void tellUltracode($, ultra, isOn))
      }
      ultra.lastCommand = undefined
    }
    return kept
  }).catch(($, e, next) => next(e))
}
