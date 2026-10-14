import type { Register } from 'claude-code'

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
// It runs no command in a chat: no command line of its own shows in its terminal.
//
// And it adds /let-them-talk, which starts the app the README's way (uvx
// let-them-talk) and opens it in the browser, with no Claude turn: see START.

const APP = 'http://localhost:8765' // Let Them Talk's default port (LTT_PORT)
const HEADERS = { 'Content-Type': 'application/json', 'X-Let-Them-Talk': '1' }
const TICK_MS = 2000
const OWN_WAIT_MS = 12000 // Claude Code makes its own within a few seconds of the turn's end
const WINDOW_MS = 300_000 // after that the conversation may no longer be cached (server: MOD_WINDOW)
const HELLO_EVERY_MS = 300_000 // so the app keeps counting this chat as having the mod
const MODEL_ASKS = 3 // turns at a chat's start the app is asked for a model (it knows by the first)

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

export const UV_LINK = 'https://docs.astral.sh/uv/'

// Variables a chat sets for what it starts: server.py's SESSION_ENV, the same
// list. The app is started without them, as from a terminal, so nothing it
// starts is taken for a part of this chat.
export const SESSION_ENV = ['CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_MESSAGING_SOCKET',
  'CLAUDE_CODE_MESSAGING_TOKEN', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_JOB_DIR',
  'CLAUDE_CODE_SESSION_ATTENDED', 'TRACEPARENT', 'TRACESTATE']

// /let-them-talk's start, run by sh with the board's address as $1. It finds
// uvx (on the PATH, or where uv's installer puts it) and starts
// `uvx let-them-talk` from the home folder in a session of its own (setsid;
// nohup where there is none, as on macOS), with no pipe or terminal of this
// chat's, so it keeps running after the chat ends. The app opens the page
// itself, and when it runs already it only opens the page and ends. This waits
// up to 15 s for it to print the address (it runs) or end, then prints
// `no-uv`, `running` or `ended <exit code>`, and below that what the app printed.
export const START = `uvx=
for f in "$(command -v uvx)" "$HOME/.local/bin/uvx" "$HOME/.cargo/bin/uvx"; do
  if [ -z "$uvx" ] && [ -n "$f" ] && [ -x "$f" ]; then uvx=$f; fi
done
if [ -z "$uvx" ]; then echo no-uv; exit 0; fi
dir=$(mktemp -d 2>/dev/null || mktemp -d -t let-them-talk) || exit 1
cd "$HOME" 2>/dev/null || cd /
unset ${SESSION_ENV.join(' ')}
run='"$0" let-them-talk > "$1/out" 2>&1; echo $? > "$1/code"'
if command -v setsid > /dev/null 2>&1; then
  setsid sh -c "$run" "$uvx" "$dir" < /dev/null > /dev/null 2>&1 &
else
  nohup sh -c "$run" "$uvx" "$dir" < /dev/null > /dev/null 2>&1 &
fi
i=0
while [ ! -s "$dir/code" ] && ! grep -q -F "$1" "$dir/out" 2> /dev/null && [ $i -lt 60 ]; do
  sleep 0.25
  i=$((i + 1))
done
if [ -s "$dir/code" ]; then echo "ended $(cat "$dir/code")"; else echo running; fi
cat "$dir/out" 2> /dev/null
rm -rf "$dir"
`

/** What /let-them-talk says, from what START printed and whether the app
 * already answered at `url` before it ran. `exitCode` is for a
 * `claude -p /let-them-talk` run from a shell. */
export function startReport(printed: string, url: string, wasRunning: boolean): { text: string; exitCode?: number } {
  const [status = '', ...rest] = printed.split('\n')
  const said = rest.join('\n').trim()
  if (status === 'no-uv') {
    return {
      text: `Let Them Talk starts with uv, which isn't installed. Install uv (${UV_LINK}), then run /let-them-talk again.`,
      exitCode: 1,
    }
  }
  const failed = status !== 'running' && status !== 'ended 0'
  if (wasRunning) return { text: `Let Them Talk is already running. ${failed ? 'Open' : 'Opening'} ${url} in your browser.` }
  if (failed) return { text: `Let Them Talk didn't start.${said ? `\n\n${said}` : ''}`, exitCode: 1 }
  const after = 'It keeps running after this chat ends.'
  if (status === 'running' && !said.includes(url)) {
    return { text: `Let Them Talk is starting. The first start downloads it, which can take a minute; then it opens in your browser at ${url}. ${after}` }
  }
  return { text: `Let Them Talk is running at ${url} and opens in your browser. ${after}` }
}

export const register: Register = on => {
  on('command.run', { command: 'let-them-talk' }, async $ => {
    const url = `http://localhost:${(await $.env.get('LTT_PORT')) || '8765'}`
    let wasRunning = false
    try {
      const page = await $.http.fetch(`${url}/`)
      wasRunning = (page.headers.server ?? '').startsWith('LetThemTalk/')
    } catch {
      // nothing answers there
    }
    try {
      const run = await $.process.run(['sh', '-c', START, 'let-them-talk', url], { timeoutMs: 30_000 })
      return startReport(run.stdout, url, wasRunning)
    } catch (error) {
      return { text: `Let Them Talk didn't start: ${error instanceof Error ? error.message : String(error)}`, exitCode: 1 }
    }
  })

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

  // Work after a turn outlives the turn's own hooks, so a timer started here does it.
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    try {
      await $.command.register({ name: 'let-them-talk', description: 'Start Let Them Talk and open it in your browser' })
    } catch {
      // refused: the suggestions below still run
    }
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
}
