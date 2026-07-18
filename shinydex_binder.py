#!/usr/bin/env python3
"""Generate the shiny-dex card binder in the acidcat brand.

Data from SHINYDEX.md + live acidcat stats. Caught shinies -> full cards (real
format/size/chunk stats + a byte-derived sigil on the teal->orange brand ramp);
Wanted -> silhouette "not yet caught" cards. Brand: ink canvas + gunmetal
grayscale, teal for structure, orange for attention (tui_theme.py); Cascadia
Code; data-theme dark/light + corner toggle. Tap a card to lift + flip.
Self-contained HTML, publishable as an Artifact.
"""
import json, re, html
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHINYDEX = ROOT / "SHINYDEX.md"
OUT = ROOT / "shinydex-binder.html"

try:
    import acidcat
except Exception:
    acidcat = None

# brand byte-map ramp (teal -> silver -> orange), from tui_theme.py PALETTE
RAMP = ["#08F9DF", "#5CD9CE", "#93C9C2", "#C9CDD3", "#D6B49E", "#E88F63", "#F56A31", "#FF4D00"]

def parse_tables(md):
    caught, wanted = [], []
    section = None
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## "):
            low = s.lower()
            section = "caught" if "synthesized" in low else "wanted" if "wanted" in low else None
            continue
        if not (s.startswith("|") and section):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("shiny", "") or set(cells[0]) <= set("-: "):
            continue
        if section == "caught" and len(cells) >= 5:
            caught.append(dict(name=cells[0], fmt=cells[1], quirk=cells[2], status=cells[3], specimen=cells[4].strip("`")))
        elif section == "wanted" and len(cells) >= 4:
            wanted.append(dict(name=cells[0], fmt=cells[1], quirk=cells[2], why=cells[3]))
    return caught, wanted

def sigil(data, cells=8, rows=5):
    """Byte-derived grid on the brand ramp. Inline SVG."""
    if not data:
        data = b"\x00"
    step = max(1, len(data) // (cells * rows))
    sq = 26
    rects = []
    for i in range(cells * rows):
        v = data[min(i * step, len(data) - 1)]
        if v < 36:
            continue
        cx, cy = (i % cells) * sq, (i // cells) * sq
        col = RAMP[min(7, v * 8 // 256)]
        op = 0.22 + 0.78 * (v / 255)
        rects.append(f'<rect x="{cx}" y="{cy}" width="{sq-3}" height="{sq-3}" rx="2" fill="{col}" fill-opacity="{op:.2f}"/>')
    W, H = cells * sq, rows * sq
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">{"".join(rects)}</svg>'

def stats_for(specimen):
    p = ROOT / "specimens" / specimen
    info = {"size": None, "fmt_label": None, "chunks": [], "warns": 0}
    raw = b""
    if not p.exists():
        return info, raw
    raw = p.read_bytes()
    info["size"] = len(raw)
    if acidcat:
        try:
            fmt, chunks, fwarns = acidcat.walk_file(str(p))
            info["fmt_label"] = fmt
            info["chunks"] = [c["id"].strip() for c in chunks]
            info["warns"] = len(fwarns) + sum(len(c.get("warnings") or []) for c in chunks)
        except Exception:
            pass
    return info, raw

def human(n):
    if n is None:
        return "?"
    for u in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} GB"

def rarity(quirk, warns, chunks):
    violating = any(k in quirk.lower() for k in ("violat", "placeholder", "inside", "negative", "truncat", "override", "gap", "surrogate", "combining", "bidi"))
    if violating or warns >= 2:
        return "holo"
    if warns >= 1 or len(chunks) >= 4:
        return "rare"
    return "common"

def build():
    caught_rows, wanted_rows = parse_tables(SHINYDEX.read_text())
    cards = []
    for r in caught_rows:
        info, raw = stats_for(r["specimen"])
        cards.append(dict(kind="caught", name=r["name"], fmt=r["fmt"], quirk=r["quirk"], status=r["status"],
                          specimen=r["specimen"], size=human(info["size"]), fmt_label=info["fmt_label"] or r["fmt"],
                          chunks=info["chunks"], warns=info["warns"], sigil=sigil(raw),
                          rarity=rarity(r["quirk"], info["warns"], info["chunks"])))
    for r in wanted_rows:
        cards.append(dict(kind="wanted", name=r["name"], fmt=r["fmt"], quirk=r["quirk"], why=r.get("why", ""), rarity="wanted"))
    caught_n = sum(c["kind"] == "caught" for c in cards)
    page = (TEMPLATE.replace("__DATA__", json.dumps(cards))
            .replace("__CAUGHT__", str(caught_n)).replace("__TOTAL__", str(len(cards))))
    OUT.write_text(page)
    print(f"wrote {OUT}  ({caught_n} caught, {len(cards)-caught_n} wanted)")

TEMPLATE = r"""<script>(function(){try{var m=localStorage.getItem("acidcat-theme");if(!m)m=matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light";document.documentElement.setAttribute("data-theme",m);}catch(e){}})();</script>
<div id="app"></div>
<style>
:root{ /* light companion */
  --bg:#E6E6E1; --panel:#ECECE7; --inset:#F1F1EC; --line:#CACCC0; --hair:#D7D8CD;
  --dim:#9A9B8F; --soft:#67685F; --ink:#1E201D; --teal:#0A7F73; --orange:#D8420A; --amber:#9A6A1E;
  --ff:"Cascadia Code","JetBrains Mono","SF Mono",Menlo,Consolas,ui-monospace,monospace;
}
:root[data-theme="dark"]{ /* brand (tui_theme.py) */
  --bg:#16181C; --panel:#101217; --inset:#0C0E12; --line:#3A3E45; --hair:#26292F;
  --dim:#565B63; --soft:#8A9099; --ink:#C9CDD3; --teal:#08F9DF; --orange:#FF4D00; --amber:#E0913E;
}
*{box-sizing:border-box;margin:0;padding:0}
#app{background:var(--bg);color:var(--ink);font-family:var(--ff);font-weight:300;font-size:14px;min-height:100vh;-webkit-font-smoothing:antialiased}
::selection{background:var(--teal);color:var(--bg)}
.sheet{max-width:1120px;margin:0 auto;padding:clamp(1.5rem,4vw,3rem) clamp(1.25rem,4vw,2.5rem) 5rem}
.head{border:1px solid var(--line);border-radius:9px;overflow:hidden;margin-bottom:1.6rem}
.head .row{display:grid;grid-template-columns:1fr auto;align-items:stretch}
.head .title{padding:0.9rem 1.1rem}
.sysmark{font-size:0.6rem;letter-spacing:0.34em;color:var(--soft);text-transform:uppercase}
.sysmark b{color:var(--teal);font-weight:500}
.head h1{font-weight:500;font-size:clamp(1.4rem,4vw,1.9rem);letter-spacing:0.02em;margin-top:0.25rem}
.head .stamp{border-left:1px solid var(--line);padding:0.9rem 1.1rem;text-align:right;font-size:0.58rem;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);display:flex;flex-direction:column;justify-content:center;gap:0.25rem}
.head .stamp b{color:var(--teal);font-weight:500}
.head .strip{border-top:1px solid var(--line);display:grid;grid-template-columns:repeat(3,1fr);font-size:0.6rem;letter-spacing:0.1em;text-transform:uppercase}
.head .strip div{padding:0.5rem 1.1rem;border-right:1px solid var(--hair);color:var(--soft)}
.head .strip div:last-child{border-right:none}
.head .strip b{color:var(--teal);font-weight:500}
.head .strip .tap{color:var(--amber)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:12px}
.card{aspect-ratio:5/7;perspective:1200px;cursor:pointer;transition:opacity .22s,filter .22s,transform .45s cubic-bezier(.2,.7,.2,1);--acc:var(--dim)}
.card.r-rare{--acc:var(--amber)} .card.r-holo{--acc:var(--orange)}
.card:focus-visible{outline:2px solid var(--teal);outline-offset:3px}
.inner{position:relative;width:100%;height:100%;transition:transform .55s cubic-bezier(.2,.7,.2,1);transform-style:preserve-3d}
.card.flip{transform:scale(1.06);z-index:20}
.card.flip .inner{transform:rotateY(180deg)}
.grid.active .card:not(.flip){opacity:.4;filter:saturate(.55)}
.face{position:absolute;inset:0;backface-visibility:hidden;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--panel);display:flex;flex-direction:column}
.card.flip .face{box-shadow:0 24px 44px -20px #000d, 0 0 0 1px color-mix(in srgb,var(--acc) 55%,transparent)}
.front{border-top:2px solid var(--acc)}
.hd{padding:9px 11px 7px;display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.nm{font-weight:500;font-size:12.5px;line-height:1.2;color:var(--ink)}
.badge{flex:none;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--teal);border:1px solid var(--line);border-radius:5px;padding:2px 6px}
.rar{position:absolute;top:9px;right:11px;font-size:8.5px;letter-spacing:0.18em;text-transform:uppercase;color:var(--acc)}
.art{flex:1;margin:2px 11px;border-radius:8px;background:radial-gradient(120% 90% at 50% 0%,color-mix(in srgb,var(--acc) 14%,transparent),transparent),var(--inset);border:1px solid var(--hair);padding:11px;display:flex;align-items:center;justify-content:center}
.stats{display:flex;gap:5px;padding:9px 11px 3px;flex-wrap:wrap}
.stat{font-size:9px;letter-spacing:0.04em;color:var(--dim);background:var(--inset);border:1px solid var(--hair);border-radius:5px;padding:2px 6px}
.stat b{color:var(--ink);font-weight:400}
.flav{padding:5px 11px 11px;font-size:10px;color:var(--soft);line-height:1.4}
/* restrained brand foil on holo, hover only */
.card.r-holo .front::after{content:"";position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen;opacity:0;transition:opacity .3s;background:linear-gradient(115deg,#08F9DF00 30%,#08F9DF20 44%,#C9CDD310 50%,#FF4D0022 58%,#FF4D0000 72%)}
.card.r-holo:hover .front::after{opacity:.85}
/* back */
.back{transform:rotateY(180deg);padding:12px;gap:5px;font-size:11px;overflow:hidden}
.tag{font-size:9px;letter-spacing:0.12em;font-weight:500;padding:2px 7px;border-radius:5px;align-self:flex-start;margin-bottom:4px}
.tag.syn{background:color-mix(in srgb,var(--teal) 18%,transparent);color:var(--teal)}
.tag.want{background:color-mix(in srgb,var(--amber) 20%,transparent);color:var(--amber)}
.brow{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid var(--hair);padding:3px 0;font-size:10px}
.brow span:first-child{color:var(--dim)} .brow span:last-child{color:var(--ink)}
.blabel{color:var(--dim);font-size:9px;letter-spacing:0.1em;text-transform:uppercase;margin-top:6px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:3px}
.chip{font-size:9px;background:var(--inset);border:1px solid var(--hair);border-radius:4px;padding:1px 5px;color:var(--soft)}
/* wanted silhouette */
.card.wanted .front{border-top-color:var(--dim);filter:grayscale(1)}
.card.wanted .nm{color:var(--dim)}
.card.wanted .art{color:var(--line)}
.silh{font-size:44px;font-weight:600;color:var(--line)}
.foot{color:var(--dim);font-size:11px;text-align:center;margin-top:2rem;letter-spacing:0.08em}
.theme-toggle{position:fixed;bottom:0.9rem;right:0.9rem;z-index:50;font-family:var(--ff);font-size:0.56rem;letter-spacing:0.22em;text-transform:uppercase;color:var(--soft);background:var(--panel);border:1px solid var(--line);padding:0.45rem 0.7rem;cursor:pointer;transition:.15s}
.theme-toggle:hover{color:var(--teal);border-color:var(--teal)}
@media(prefers-reduced-motion:reduce){.card,.inner{transition:none!important}}
</style>
<button class="theme-toggle" onclick="(function(){var r=document.documentElement,n=r.getAttribute('data-theme')==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{localStorage.setItem('acidcat-theme',n)}catch(e){}})()">theme</button>
<script>
const CARDS=__DATA__;const app=document.getElementById('app');
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function caught(c){
  return `<div class="card r-${c.rarity}" tabindex="0" role="button" aria-label="${esc(c.name)}, tap to flip">
   <div class="inner">
    <div class="face front">
      <span class="rar">${c.rarity}</span>
      <div class="hd"><div class="nm">${esc(c.name)}</div><span class="badge">${esc(c.fmt)}</span></div>
      <div class="art">${c.sigil}</div>
      <div class="stats"><span class="stat"><b>${esc(c.size)}</b></span><span class="stat">chunks <b>${c.chunks.length}</b></span>${c.warns?`<span class="stat" style="color:var(--orange)">&#9888; <b>${c.warns}</b></span>`:''}</div>
      <div class="flav">${esc(c.quirk)}</div>
    </div>
    <div class="face back">
      <span class="tag ${c.status.includes('WANT')?'want':'syn'}">${esc(c.status)}</span>
      <div class="brow"><span>format</span><span>${esc(c.fmt_label)}</span></div>
      <div class="brow"><span>size</span><span>${esc(c.size)}</span></div>
      <div class="brow"><span>warnings</span><span>${c.warns}</span></div>
      <div class="blabel">chunks</div><div class="chips">${(c.chunks.length?c.chunks:['&mdash;']).map(x=>`<span class="chip">${esc(x)}</span>`).join('')}</div>
      <div class="blabel">specimen</div><div class="chip" style="word-break:break-all">${esc(c.specimen)}</div>
    </div>
   </div></div>`;
}
function wanted(c){
  return `<div class="card wanted" tabindex="0" role="button" aria-label="${esc(c.name)}, not yet caught">
   <div class="inner">
    <div class="face front">
      <span class="rar">wanted</span>
      <div class="hd"><div class="nm">${esc(c.name)}</div><span class="badge" style="color:var(--dim);border-color:var(--line)">${esc(c.fmt)}</span></div>
      <div class="art"><div class="silh">?</div></div>
      <div class="flav">not yet caught</div>
    </div>
    <div class="face back">
      <span class="tag want">WANT</span>
      <div class="brow"><span>format</span><span>${esc(c.fmt)}</span></div>
      <div class="blabel">the quirk</div><div class="flav" style="padding:2px 0">${esc(c.quirk)}</div>
      <div class="blabel">why it's wanted</div><div class="flav" style="padding:2px 0">${esc(c.why)}</div>
    </div>
   </div></div>`;
}
app.innerHTML=`<div class="sheet">
 <div class="head"><div class="row">
   <div class="title"><div class="sysmark"><b>acidcat</b> // field guide</div><h1>The Shiny-Dex</h1></div>
   <div class="stamp"><b>caught ${'__CAUGHT__'} / ${'__TOTAL__'}</b>rev 2026.07</div></div>
   <div class="strip"><div>caught <b>__CAUGHT__</b></div><div>total <b>__TOTAL__</b></div><div class="tap"><b class="tap">tap a card to flip</b></div></div></div>
 <div class="grid">${CARDS.map(c=>c.kind==='caught'?caught(c):wanted(c)).join('')}</div>
 <div class="foot">generated from SHINYDEX.md + live acidcat stats &middot; gotta parse 'em all</div>
</div>`;
const grid=app.querySelector('.grid');
function toggle(card){
  const on=card.classList.contains('flip');
  grid.querySelectorAll('.card.flip').forEach(x=>x.classList.remove('flip'));
  if(!on) card.classList.add('flip');
  grid.classList.toggle('active', !!grid.querySelector('.card.flip'));
}
grid.querySelectorAll('.card').forEach(c=>{
  c.addEventListener('click',()=>toggle(c));
  c.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(c);}});
});
</script>
"""

if __name__ == "__main__":
    build()
