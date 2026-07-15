"""FastAPI app: natural-language control of the ANDONT tower light.

POST /run    {"text": "...", "buzzer": false} -> Haiku translates to pattern
             steps (patterns.py schema), runner executes in background.
POST /reset  stop any run, all lights/buzzer off.
GET  /status runner state.
GET  /       input page (RUN / RESET, speaker toggle).

API key: ANTHROPIC_API_KEY env var, or a .env file in this directory
containing ANTHROPIC_API_KEY=sk-ant-...

Run:  ./.venv/bin/uvicorn app:app --port 8321
"""

import json
import os
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from patterns import PatternRunner

# Load .env if the key isn't already in the environment
if not os.environ.get("ANTHROPIC_API_KEY"):
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()

MODEL = "claude-sonnet-4-6"

STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["steady", "blink", "alternate", "chase"]},
                    "colors": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["red", "orange", "green", "blue"]},
                    },
                    "on_ms": {"type": "integer"},
                    "off_ms": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "buzzer": {"type": "boolean"},
                    "width": {"type": "integer"},
                    "overlap_ms": {"type": "integer"},
                },
                "required": ["mode", "colors", "on_ms", "off_ms", "duration_s",
                             "buzzer", "width", "overlap_ms"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}

SYSTEM = """\
You translate natural-language light-pattern requests into JSON steps for a
4-lamp andon tower (top to bottom: red, orange, green, blue).

Modes:
- steady: all listed colors on solid for duration_s
- blink: listed colors flash together (on_ms lit, off_ms dark)
- alternate: colors take turns, on_ms each, off_ms dark between
- chase: a lit window runs through the color list with no dark gap. Direction
  comes from color order: ["red","orange","green","blue"] chases DOWN the
  stack, reversed chases UP. width = lamps lit at once (1 or 2). overlap_ms
  lights the next lamp a few ms before the previous drops, softening the
  transition (10-30 is a nice bleed; 0 = crisp).

Every step must include width and overlap_ms — use 1 and 0 unless the mode is
chase and the request calls for a pair or a smooth transition.

Rules:
- "all colors" / "all lights" means ["red","orange","green","blue"] in that order.
- Minimum on_ms/off_ms is 5. If unspecified, use 250.
- If duration is unspecified, use 5 seconds.
- "flash X and Y alternately" -> mode alternate with those two colors.
- Set buzzer true only if the request explicitly asks for sound/beep/buzzer.
- Multiple phases in one request become multiple steps in order.
- Speed words map to timings: "fast"/"rapid" ~50-80ms, "very fast" ~20-30ms,
  "slow"/"calm" ~500-1000ms, "pulse" -> blink with equal on/off.
- "police lights" -> red and blue.
- DECOMPOSE rotating requests: if the user asks for patterns that change,
  alternate, rotate, or vary every N seconds across a total duration, output
  total/N SEPARATE steps of N seconds each, and make each step genuinely
  different — vary the mode (alternate vs blink vs chase), the grouping
  (e.g. blink [red] then blink [blue] as consecutive short steps to make
  RRR/BBB volleys), and/or the timing. Never repeat one identical step for
  the whole duration when variety was requested.
- Steps run back-to-back with no gap, so consecutive short steps can build
  compound rhythms (e.g. 0.5s blink [red] + 0.5s blink [blue], repeated).

Worked examples (fields omitted here for brevity — YOUR output always includes
every field):

1) "FAST police lights, changing patterns every 5 seconds, for 30 seconds"
   Six 5s phases, each genuinely different. Phase 2 is an RRR/BBB volley built
   from repeated short steps:
   - alternate [red,blue] on 60 off 60, 5s
   - volley: blink [red] on 70 off 70 for 0.5s, then blink [blue] on 70 off 70
     for 0.5s — repeat the pair 5 times (10 steps totaling 5s)
   - blink [red,blue] together on 60 off 60, 5s
   - chase [red,blue,red,blue... just [red,blue]] width 1 overlap 0, on 60, 5s
   - alternate [blue,red] on 40 off 80 (syncopated), 5s
   - blink [red,blue] on 30 off 30 (frantic finale), 5s

2) "traffic light cycle for 30 seconds"
   Repeat this trio until 30s is filled:
   - steady [green] 4s
   - steady [orange] 1.5s
   - steady [red] 4s

3) chase vocabulary:
   - "chase down": chase [red,orange,green,blue] width 1 overlap_ms 0
   - "chase up": chase [blue,green,orange,red] width 1 overlap_ms 0
   - "smooth/flowing chase": same but overlap_ms 15-30
   - "two-lamp chase" / "sliding pair": width 2
   - "bounce": alternate chase-down and chase-up steps back to back"""

app = FastAPI(title="andont")
runner = PatternRunner()
client = anthropic.Anthropic()


class RunRequest(BaseModel):
    text: str
    buzzer: bool = False


@app.post("/run")
def run(req: RunRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "empty command")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not set — add it to the environment or a .env file next to app.py")
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": STEP_SCHEMA}},
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(500, "Anthropic API key missing or invalid")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"translation failed: {e.message}")

    program = json.loads(next(b.text for b in response.content if b.type == "text"))
    steps = program["steps"]
    if not steps:
        raise HTTPException(400, "couldn't translate that into a light pattern")
    if not req.buzzer:  # speaker toggle off -> strip any buzzer the model set
        for s in steps:
            s["buzzer"] = False
    runner.run(steps, allow_buzzer=req.buzzer)
    return {"status": "running", "steps": steps}


@app.post("/reset")
def reset():
    runner.reset()
    return {"status": "idle"}


@app.get("/status")
def status():
    return {"status": runner.status}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>andont</title>
<style>
  :root { --bg:#0D1117; --panel:#161B22; --border:#30363D; --text:#E6EDF3;
          --muted:#8B949E; --accent:#58A6FF; --green:#3FB950; --red:#F85149; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:16px/1.5 -apple-system,system-ui,sans-serif;
         display:flex; justify-content:center; padding-top:12vh; }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:12px;
          padding:28px; width:min(560px,92vw); }
  h1 { font-size:18px; margin:0 0 16px; font-weight:600; }
  h1 span { color:var(--muted); font-weight:400; }
  textarea { width:100%; height:96px; resize:vertical; background:var(--bg);
             color:var(--text); border:1px solid var(--border); border-radius:8px;
             padding:12px; font:inherit; }
  textarea:focus { outline:none; border-color:var(--accent); }
  .row { display:flex; gap:10px; margin-top:14px; align-items:center; }
  button { font:inherit; font-weight:600; border-radius:8px; padding:10px 22px;
           cursor:pointer; border:1px solid var(--border); }
  #run { background:var(--green); color:#0D1117; border-color:transparent; }
  #run:disabled { opacity:.5; cursor:wait; }
  #resetBtn { background:transparent; color:var(--red); border-color:var(--red); }
  #spk { background:transparent; font-size:20px; padding:8px 12px; margin-left:auto; }
  #spk.on { border-color:var(--accent); }
  #msg { margin-top:14px; font-size:14px; color:var(--muted); min-height:20px;
         white-space:pre-wrap; }
  #msg.err { color:var(--red); }
</style></head><body>
<div class="card">
  <h1>andont <span>&mdash; tell the light what to do</span></h1>
  <textarea id="cmd" placeholder="e.g. flash orange and green alternately for 1 minute with 60ms on and 60ms off, then run an all-color loop for 3 seconds at 20ms per lamp"></textarea>
  <div class="row">
    <button id="run">RUN</button>
    <button id="resetBtn">RESET</button>
    <button id="spk" title="Buzzer off">&#128263;</button>
  </div>
  <div id="msg"></div>
</div>
<script>
const cmd = document.getElementById('cmd'), msg = document.getElementById('msg');
const runBtn = document.getElementById('run'), spk = document.getElementById('spk');
let buzzer = false;

spk.onclick = () => {
  buzzer = !buzzer;
  spk.innerHTML = buzzer ? '&#128266;' : '&#128263;';
  spk.title = buzzer ? 'Buzzer on' : 'Buzzer off';
  spk.classList.toggle('on', buzzer);
};

async function post(path, body) {
  const r = await fetch(path, { method:'POST', headers:{'Content-Type':'application/json'},
                                body: body ? JSON.stringify(body) : null });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

runBtn.onclick = async () => {
  msg.className = ''; msg.textContent = 'Translating…'; runBtn.disabled = true;
  try {
    const data = await post('/run', { text: cmd.value, buzzer });
    msg.textContent = 'Running ' + data.steps.length + ' step(s):\\n' +
      data.steps.map(s => `• ${s.mode} [${s.colors.join(', ')}] ${s.on_ms}ms on` +
        (s.mode==='blink'||s.mode==='alternate' ? `/${s.off_ms}ms off` : '') +
        ` for ${s.duration_s}s` + (s.buzzer ? ' +buzzer' : '')).join('\\n');
  } catch (e) {
    msg.className = 'err'; msg.textContent = e.message;
  } finally { runBtn.disabled = false; }
};

document.getElementById('resetBtn').onclick = async () => {
  try { await post('/reset'); msg.className=''; msg.textContent = 'Reset — all off.'; }
  catch (e) { msg.className='err'; msg.textContent = e.message; }
};

cmd.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) runBtn.click();
});
</script>
</body></html>"""
