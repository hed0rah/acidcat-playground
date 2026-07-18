#!/usr/bin/env python3
"""Interactive audio-format landscape board, in the acidcat brand.

Brand palette from acidcat/src/acidcat/tui_theme.py (ink canvas + gunmetal
grayscale, teal for structure, orange for attention). Style foundation from the
docs/formats/*-anatomy.html sheets: IBM Plex Mono, data-theme dark/light + a
corner toggle, datasheet layout. Self-contained HTML; publishable as an Artifact
(font falls back to ui-monospace where the CDN is blocked).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "landscape-map.html"

# status: have | partial | gap
CATS = [
 ("Distribution / playback", [
    ("MP3", "have", "ID3v1/v2.2-2.4, APEv2, Xing/VBRI/LAME"),
    ("AAC / M4A", "have", "iTunes ilst atoms"),
    ("Ogg Vorbis", "have", ""), ("Opus", "have", ""),
    ("FLAC", "have", "STREAMINFO/VORBIS/PICTURE/SEEKTABLE/CUESHEET"),
    ("WAV / AIFF", "have", ""),
    ("ALAC", "partial", "tag-only"),
    ("WMA / ASF", "gap", ""),
    ("WavPack / Monkey's / TAK / TTA / Musepack", "gap", "the lossless long tail"),
 ]),
 ("Production - sample WAV/AIFF", [
    ("PCM WAV", "have", ""), ("RF64 / BW64", "have", "ds64 sentinel"),
    ("BWF (bext)", "have", "v0-v2"), ("ACIDized (acid)", "have", "your loops"),
    ("cue / smpl", "have", ""), ("cart", "have", ""),
    ("Apple Loops (basc)", "have", ""),
    ("iXML", "partial", ""),
    ("vendor chunks: LGWV / ResU / AFAn / clm / strc / FLLR", "gap", "to catalogue - the fingerprint gold"),
 ]),
 ("DAW project files", [
    ("Bitwig", "have", ""),
    ("Ableton .als/.adv/.adg + .asd", "gap", "gzip XML + sidecar"),
    ("FL Studio .flp", "gap", ""), ("Logic .logicx / EXS24", "gap", ""),
    ("Pro Tools", "gap", ""), ("Cubase / Nuendo", "gap", ""),
    ("Reaper", "gap", ""), ("Studio One", "gap", ""),
    ("Reason", "gap", ""), ("Renoise", "gap", ""),
 ]),
 ("Samplers", [
    ("NI nksf / NCW", "have", "FastLZ + NKS MessagePack"),
    ("SF2 / SF3", "have", ""), ("REX / RX2", "have", ""),
    ("Kontakt .nki/.nkm", "partial", "unencrypted only"),
    ("DecentSampler / SFZ", "gap", "open, easy to add"),
    ("TX16Wx / Battery / HALion", "gap", ""),
    ("Akai MPC .PGM / .SND (vintage, binary)", "gap", "generational: 2000XL/1000 break"),
    ("Akai MPC .XPM / .XPJ (MPC Software, XML)", "gap", "the binary->XML jump"),
    ("other hardware (E-mu / Roland / Ensoniq)", "gap", ""),
 ]),
 ("Synth / plugin presets", [
    ("Serum", "have", ""), ("Vital", "have", "mod matrix"),
    ("VST2 FXP / FXB", "have", ""),
    ("Massive / Sylenth / u-he / Omnisphere", "gap", ""),
    ("VST3 .vstpreset", "gap", ""), ("AU .aupreset", "gap", ""),
 ]),
 ("Wavetables", [
    ("Bitwig .wt", "have", "vawt"), ("Vital", "have", ""),
    ("Serum WAV + clm", "partial", ""), ("Ableton", "gap", ""),
 ]),
 ("Trackers", [
    ("MOD / XM / IT", "have", "structure; no PCM decode yet"),
    ("S3M", "gap", "we have cracktros - low-hanging"),
    ("669 / MTM / PTM / long tail", "gap", ""),
 ]),
 ("Field / broadcast / post", [
    ("BWF / iXML / RF64", "have", ""),
    ("MOV / MP4 audio", "partial", ""),
    ("poly-WAV", "gap", ""), ("MXF", "gap", ""),
 ]),
 ("DJ metadata", [
    ("Serato (GEOB in ID3, crates)", "gap", ""),
    ("Rekordbox (.xml / .pdb)", "gap", ""),
    ("Traktor (.nml)", "gap", ""), ("Mixed In Key", "gap", ""),
 ]),
 ("Sidecars", [
    (".cue", "partial", ""), (".asd (Ableton)", "gap", ""),
    (".reapeaks / .sfk peaks", "gap", ""), (".nkc", "gap", ""),
 ]),
 ("SDR / IQ  (the audio-RF bridge - proposed)", [
    ("SigMF (.sigmf-data + .sigmf-meta)", "partial", "sigmf_walk() prototype in nb 03"),
    ("cu8 (RTL-SDR native)", "gap", "headerless; geometry + filename metadata"),
    ("cf32 (GNU Radio / GQRX)", "gap", ""),
    ("IQ-in-WAV (SDR# / HDSDR, auxi chunk)", "gap", "RIFF - the grammar CAN bite here"),
    ("PortaPack .C16 + .TXT", "gap", ""),
 ]),
]

DATA = json.dumps(CATS)
counts = {"have":0,"partial":0,"gap":0}
for _, items in CATS:
    for _,s,_ in items: counts[s]+=1
total = sum(counts.values())

HTML = r"""<script>(function(){try{var m=localStorage.getItem("acidcat-theme");if(!m)m=matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light";document.documentElement.setAttribute("data-theme",m);}catch(e){}})();</script>
<div id="app"></div>
<style>
/* light (companion) */
:root{
  --bg:#E6E6E1; --panel:#ECECE7; --inset:#F1F1EC; --line:#CACCC0; --hair:#D7D8CD;
  --dim:#9A9B8F; --soft:#67685F; --ink:#1E201D;
  --teal:#0A7F73; --orange:#D8420A; --amber:#9A6A1E;
  --ff:"Cascadia Code","JetBrains Mono","SF Mono",Menlo,Consolas,ui-monospace,monospace;
}
/* dark = the brand (tui_theme.py) */
:root[data-theme="dark"]{
  --bg:#16181C; --panel:#101217; --inset:#0C0E12; --line:#3A3E45; --hair:#26292F;
  --dim:#565B63; --soft:#8A9099; --ink:#C9CDD3;
  --teal:#08F9DF; --orange:#FF4D00; --amber:#E0913E;
}
*{box-sizing:border-box;margin:0;padding:0}
#app{background:var(--bg);color:var(--ink);font-family:var(--ff);font-weight:300;
  line-height:1.6;font-size:14px;min-height:100vh;-webkit-font-smoothing:antialiased}
::selection{background:var(--teal);color:var(--bg)}
.sheet{max-width:1080px;margin:0 auto;padding:clamp(1.5rem,4vw,3rem) clamp(1.25rem,4vw,2.5rem) 5rem}
/* header */
.head{border:1px solid var(--line);border-radius:9px;overflow:hidden}
.head .row{display:grid;grid-template-columns:1fr auto;align-items:stretch}
.head .title{padding:0.9rem 1.1rem}
.sysmark{font-size:0.6rem;letter-spacing:0.34em;color:var(--soft);text-transform:uppercase}
.head h1{font-weight:500;font-size:clamp(1.4rem,4vw,1.9rem);letter-spacing:0.02em;margin-top:0.25rem}
.head .stamp{border-left:1px solid var(--line);padding:0.9rem 1.1rem;text-align:right;
  font-size:0.58rem;letter-spacing:0.14em;text-transform:uppercase;color:var(--dim);
  display:flex;flex-direction:column;justify-content:center;gap:0.25rem}
.head .stamp b{color:var(--teal);font-weight:500}
.head .strip{border-top:1px solid var(--line);display:grid;grid-template-columns:repeat(3,1fr);
  font-size:0.6rem;letter-spacing:0.1em;text-transform:uppercase}
.head .strip div{padding:0.5rem 1.1rem;border-right:1px solid var(--hair);color:var(--soft)}
.head .strip div:last-child{border-right:none}
.head .strip b{font-weight:500}
.strip .t{color:var(--teal)} .strip .a{color:var(--amber)} .strip .o{color:var(--orange)}
.lede{color:var(--soft);max-width:76ch;font-size:0.82rem;line-height:1.7;margin:1.5rem 0 1.8rem}
.lede b{color:var(--ink);font-weight:500}
/* filter bar */
.bar{display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-bottom:1.8rem}
.btn{background:var(--panel);border:1px solid var(--line);color:var(--soft);
  font-family:var(--ff);font-size:0.62rem;letter-spacing:0.14em;text-transform:uppercase;
  padding:0.45rem 0.8rem;cursor:pointer;display:flex;gap:0.5rem;align-items:center;transition:.15s}
.btn:hover{color:var(--ink);border-color:var(--soft)}
.btn.on{color:var(--ink);border-color:var(--teal)}
.btn .n{color:var(--dim);font-variant-numeric:tabular-nums}
.sw{width:0.55rem;height:0.55rem}
.sw.have{background:var(--teal)} .sw.partial{background:var(--amber)} .sw.gap{background:var(--dim)}
/* sections */
.sec{font-size:0.74rem;letter-spacing:0.08em;text-transform:lowercase;font-weight:400;
  color:var(--soft);margin:2.3rem 0 0.8rem;display:flex;align-items:center;gap:0.7rem}
.sec::after{content:"";flex:1;height:1px;background:var(--line)}
.sec .c{color:var(--dim);font-weight:400;letter-spacing:0.1em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(248px,1fr));gap:8px}
.card{border:1px solid var(--line);border-left:2px solid var(--dim);border-radius:8px;
  background:var(--panel);padding:0.7rem 0.9rem;transition:.12s}
.card.have{border-left-color:var(--teal)} .card.partial{border-left-color:var(--amber)}
.card.gap{border-left-color:var(--dim)}
.card:hover{background:var(--inset);border-color:var(--soft)}
.card .ct{display:flex;justify-content:space-between;align-items:baseline;gap:0.6rem}
.card .fmt{font-size:0.78rem;color:var(--ink);line-height:1.35;min-width:0;overflow-wrap:anywhere}
.card .note{font-size:0.66rem;color:var(--dim);margin-top:0.35rem;line-height:1.5;overflow-wrap:anywhere}
.card .st{font-size:0.54rem;letter-spacing:0.16em;text-transform:uppercase;flex:none;margin-top:0.1rem}
.card.have .st{color:var(--teal)} .card.partial .st{color:var(--amber)} .card.gap .st{color:var(--dim)}
.card.hide{display:none}
footer{margin-top:3rem;padding-top:0.9rem;border-top:1px solid var(--ink);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;
  font-size:0.56rem;letter-spacing:0.12em;text-transform:uppercase;color:var(--dim)}
.theme-toggle{position:fixed;bottom:0.9rem;right:0.9rem;z-index:50;font-family:var(--ff);
  font-size:0.56rem;letter-spacing:0.22em;text-transform:uppercase;color:var(--soft);
  background:var(--panel);border:1px solid var(--line);padding:0.45rem 0.7rem;cursor:pointer;transition:.15s}
.theme-toggle:hover{color:var(--teal);border-color:var(--teal)}
</style>
<button class="theme-toggle" onclick="(function(){var r=document.documentElement,n=r.getAttribute('data-theme')==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{localStorage.setItem('acidcat-theme',n)}catch(e){}})()">theme</button>
<script>
const CATS=__DATA__;const app=document.getElementById('app');let filter='all';
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function render(){
  app.querySelector('.body').innerHTML = CATS.map(([name,items])=>{
    const have=items.filter(i=>filter==='all'||i[1]===filter);
    const cards=items.map(([fmt,st,note])=>
      `<div class="card ${st} ${filter!=='all'&&filter!==st?'hide':''}">
        <div class="ct"><span class="fmt">${esc(fmt)}</span><span class="st">${st}</span></div>${note?`<div class="note">${esc(note)}</div>`:''}
      </div>`).join('');
    return `<div class="sec">${esc(name)} <span class="c">${items.length}</span></div><div class="grid">${cards}</div>`;
  }).join('');
}
app.innerHTML=`<div class="sheet">
 <div class="head"><div class="row">
   <div class="title"><div class="sysmark"><span style="color:var(--teal)">acidcat</span> // format reference</div><h1>Audio Format Landscape</h1></div>
   <div class="stamp"><b>coverage board</b>rev 2026.07</div></div>
   <div class="strip">
     <div>have <b class="t">__HAVE__</b></div><div>partial <b class="a">__PARTIAL__</b></div><div>gap <b class="o">__GAP__</b></div>
   </div></div>
 <p class="lede">What acidcat parses today, and where the gaps are. The gaps are the roadmap; the per-tool <b>fingerprint</b> layer (which software writes which tell) drops in once the research is folded in.</p>
 <div class="bar">
   <button class="btn on" data-f="all">all <span class="n">__TOTAL__</span></button>
   <button class="btn" data-f="have"><span class="sw have"></span>have <span class="n">__HAVE__</span></button>
   <button class="btn" data-f="partial"><span class="sw partial"></span>partial <span class="n">__PARTIAL__</span></button>
   <button class="btn" data-f="gap"><span class="sw gap"></span>gap <span class="n">__GAP__</span></button>
 </div>
 <div class="body"></div>
 <footer><span>acidcat . landscape</span><span>filter . gaps are the roadmap</span></footer>
</div>`;
render();
app.querySelectorAll('.btn').forEach(b=>b.onclick=()=>{filter=b.dataset.f;app.querySelectorAll('.btn').forEach(x=>x.classList.toggle('on',x===b));render();});
</script>
"""
OUT.write_text(HTML.replace("__DATA__",DATA).replace("__TOTAL__",str(total))
    .replace("__HAVE__",str(counts["have"])).replace("__PARTIAL__",str(counts["partial"]))
    .replace("__GAP__",str(counts["gap"])))
print(f"wrote {OUT}  ({total}: {counts['have']} have / {counts['partial']} partial / {counts['gap']} gap)")

if __name__ == "__main__":
    pass
