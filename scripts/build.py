#!/usr/bin/env python3
"""Rebuild data.json, README.md and the animated banners from live GitHub data.

Runs in GitHub Actions on a schedule (see .github/workflows/refresh.yml).
Output is deterministic for a given set of data, so nothing is committed
unless something on the profile actually changed.
"""
import datetime, json, os, random, sys, urllib.request

LOGIN = 'scuba3198'
SITE = f'https://{LOGIN}.github.io/{LOGIN}/'
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QUERY = '''query($login: String!) { user(login: $login) {
  pinnedItems(first: 6, types: REPOSITORY) { nodes { ... on Repository { name owner { login } } } }
  repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, orderBy: {field: PUSHED_AT, direction: DESC}) {
    nodes { name description isFork stargazerCount forkCount pushedAt createdAt primaryLanguage { name } parent { nameWithOwner } }
  }
} }'''


def api(url, payload=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None,
                                 headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'profile-dive-build'})
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def fetch(old):
    """Return (repos, pinned). GraphQL first, public REST as a fallback."""
    fixture = os.environ.get('DIVE_FIXTURE')  # offline input, for testing the script without the network
    try:
        if fixture:
            with open(fixture) as fh:
                res = json.load(fh)
        else:
            res = api('https://api.github.com/graphql', {'query': QUERY, 'variables': {'login': LOGIN}})
        user = res['data']['user']
        repos = [{
            'n': r['name'], 'l': (r['primaryLanguage'] or {}).get('name') or 'Other',
            's': r['stargazerCount'], 'fk': r['forkCount'], 'd': r['pushedAt'] or r['createdAt'],
            't': r['description'] or '', 'fork': r['isFork'], 'f': (r['parent'] or {}).get('nameWithOwner', ''),
        } for r in user['repositories']['nodes']]
        pinned = [p['name'] for p in user['pinnedItems']['nodes']
                  if p and (p.get('owner') or {}).get('login', '').lower() == LOGIN]
        return repos, pinned
    except Exception as err:  # keep pinned repos and fork parents from the last good run
        print('GraphQL failed, falling back to REST:', err, file=sys.stderr)
        parents = {r['n']: r.get('f', '') for r in old.get('repos', [])}
        rest = api(f'https://api.github.com/users/{LOGIN}/repos?per_page=100&sort=pushed')
        repos = [{
            'n': r['name'], 'l': r['language'] or 'Other', 's': r['stargazers_count'], 'fk': r['forks_count'],
            'd': r['pushed_at'] or r['created_at'], 't': r['description'] or '', 'fork': r['fork'],
            'f': parents.get(r['name'], ''),
        } for r in rest]
        return repos, old.get('pinned', [])


try:
    with open('data.json') as fh:
        old = json.load(fh)
except (OSError, ValueError):
    old = {}

repos, pinned = fetch(old)
repos = [r for r in repos if r['n'].lower() != LOGIN]  # the profile repo itself is not a project
repos.sort(key=lambda r: (r['d'], r['n']), reverse=True)
data = {'login': LOGIN, 'pinned': pinned, 'repos': repos}
unchanged = all(old.get(k) == v for k, v in data.items())
data['generated'] = old['generated'] if unchanged and old.get('generated') else \
    datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
with open('data.json', 'w') as fh:
    json.dump(data, fh, indent=1, ensure_ascii=False)
    fh.write('\n')

try:  # keep the site's avatar current; never fail the build over it
    req = urllib.request.Request(f'https://github.com/{LOGIN}.png?size=160', headers={'User-Agent': 'profile-dive-build'})
    if not os.environ.get('DIVE_FIXTURE'):
        with urllib.request.urlopen(req, timeout=30) as res:
            img = res.read()
        if img and (not os.path.exists('avatar.png') or open('avatar.png', 'rb').read() != img):
            open('avatar.png', 'wb').write(img)
except Exception as err:
    print('Avatar refresh skipped:', err, file=sys.stderr)

# ---------- derived figures ----------
WORDS = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
         'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen', 'Twenty']
word = lambda n: WORDS[n] if 0 <= n < len(WORDS) else str(n)
xml = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

own = [r for r in repos if not r['fork']]
COLORS = {'TypeScript': '#55a8ff', 'JavaScript': '#f4dc55', 'ReScript': '#ff6478', 'Rust': '#f0a878', 'C#': '#63d977',
          'PowerShell': '#b693ff', 'Shell': '#8fe6cb'}
EXTRA = ['#7fd4ff', '#ffa3d1', '#c9f27a', '#ffc46b', '#9db4ff']
tally = {}
for r in repos:
    if r['l'] != 'Other':
        tally[r['l']] = tally.get(r['l'], 0) + 1
ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
N_LANGS, N_LANGED = len(ranked), sum(tally.values())
if len(ranked) > 7:
    ranked = ranked[:6] + [('Other', sum(c for _, c in ranked[6:]))]
LANGS = []
for name, count in ranked:
    colour = '#8aa3ad' if name == 'Other' else COLORS.get(name) or EXTRA[len(LANGS) % len(EXTRA)]
    LANGS.append((xml(name), count, colour))
if not LANGS:
    LANGS, N_LANGED = [('No code yet', 1, '#8aa3ad')], 1
LANG_HEAD = f"{word(N_LANGS)} language{'' if N_LANGS == 1 else 's'}, one diver."
LANG_ARIA = 'Repositories by primary language: ' + ', '.join(f'{n} {c}' for n, c, _ in LANGS) + '.'


def stat(x, value, label):
    value = str(value)
    return (f'<text class="num" x="{x}" y="442">{value}</text>'
            f'<text class="mono" x="{x + 39 * len(value) + 5}" y="438" style="font-size:14px" fill="#d3f1f2">{label}</text>')


STATS = (stat(62, len(own), 'BUILT FROM SCRATCH') + stat(430, N_LANGS, 'LANGUAGES')
         + stat(690, sum(r['s'] for r in repos), 'STARS EARNED'))

# the three repos with the most stars + forks, for the deep-water banner
TOP = [r for r in sorted(sorted(repos, key=lambda r: r['d'], reverse=True), key=lambda r: -(r['s'] + r['fk'])) if r['s'] + r['fk']][:3]
ABYSS_ARIA = ('Most starred: ' + ', '.join(f"{r['n']} ({r['s']} stars, {r['fk']} forks)" for r in TOP) + '. ' if TOP else '') + 'Open the full interactive dive.'

# ---------- README ----------
cell = lambda s: s.replace('|', '\\|').replace('\n', ' ').strip()
featured = sorted([r for r in own if r['t']], key=lambda r: r['d'], reverse=True)
featured.sort(key=lambda r: (pinned.index(r['n']) if r['n'] in pinned else len(pinned), -(r['s'] + r['fk'])))
rows = '\n'.join(
    f"| [{r['n']}](https://github.com/{LOGIN}/{r['n']}) | {cell(r['t'])} | {r['l']} | {r['s'] or ''} |" for r in featured[:8])
readme = f'''<a href="{SITE}"><img src="assets/surface.svg" width="100%" alt="{LOGIN}: Mumukshu D.C, Nepal. I build small, sharp tools: browser extensions, Windows utilities and trading helpers for NEPSE."></a>
<img src="assets/languages.svg" width="100%" alt="{LANG_ARIA}">

### Things I built from nothing

| Project | What it does | Built with | ★ |
| --- | --- | --- | --- |
{rows}

<a href="{SITE}"><img src="assets/abyss.svg" width="100%" alt="{ABYSS_ARIA}"></a>

<sub>This profile rebuilds itself from live GitHub data every ten minutes. Source: <a href="scripts/build.py">scripts/build.py</a>.</sub>
'''
with open('README.md', 'w') as fh:
    fh.write(readme)

# ---------- banners ----------
os.makedirs('assets', exist_ok=True)
random.seed(3198)
SANS = "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
RM = "@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }"

def bubbles(n, W, H, op=.55):
    out = []
    for _ in range(n):
        x, r = random.uniform(10, W - 10), random.uniform(2, 8)
        d, dl = random.uniform(5, 12), random.uniform(0, 12)
        out.append(f'<g class="bub" style="animation-duration:{d:.1f}s;animation-delay:-{dl:.1f}s"><circle cx="{x:.0f}" cy="{H+20}" r="{r:.1f}" fill="none" stroke="#dcfffc" stroke-opacity="{op}"/><circle cx="{x-r*.35:.1f}" cy="{H+20-r*.35:.1f}" r="{r*.22:.1f}" fill="#fff" fill-opacity=".6"/></g>')
    return "\n".join(out)

def plankton(n, W, H):
    cols = ['#5cf2e0', '#ffb84a', '#b693ff', '#5cf2e0']
    out = []
    for _ in range(n):
        x, y, r = random.uniform(0, W), random.uniform(0, H), random.uniform(1, 2.8)
        out.append(f'<circle class="tw" cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="{random.choice(cols)}" style="animation-duration:{random.uniform(2,5):.1f}s;animation-delay:-{random.uniform(0,5):.1f}s"/>')
    return "\n".join(out)

def school(n, y, color, dur, delay, direction=1, scale=1.0):
    fish = []
    for i in range(n):
        dx, dy, s = random.uniform(-110, 110), random.uniform(-38, 38), random.uniform(.8, 1.3) * scale
        fish.append(f'<g transform="translate({dx:.0f} {dy:.0f}) scale({s:.2f})"><ellipse rx="11" ry="4.2"/><path class="tail" d="M-9 0 L-19 -6 L-19 6 Z" style="animation-delay:-{random.uniform(0,.5):.2f}s"/></g>')
    cls = 'swimR' if direction > 0 else 'swimL'
    flip = '' if direction > 0 else ' transform="scale(-1 1)"'
    return f'<g class="{cls}" style="animation-duration:{dur}s;animation-delay:-{delay}s"><g transform="translate(0 {y})"><g fill="{color}"{flip}>{"".join(fish)}</g></g></g>'

def jelly(x, y, color, s=1.0, dur=7, delay=0):
    tents = "".join(f'<path d="M{i*9} 6 q-6 14 0 28 q6 14 0 28" class="tent" style="animation-delay:-{abs(i)*.3:.1f}s"/>' for i in range(-2, 3))
    return f'''<g transform="translate({x} {y}) scale({s})"><g class="jel" style="animation-duration:{dur}s;animation-delay:-{delay}s">
<circle r="60" fill="{color}" fill-opacity=".12"/><g class="beat"><path d="M-28 6 C-28 -34 28 -34 28 6 Q0 14 -28 6 Z" fill="{color}" fill-opacity=".38" stroke="{color}" stroke-width="1.3"/></g>
<g fill="none" stroke="{color}" stroke-width="1.2" stroke-opacity=".8">{tents}</g></g></g>'''

COMMON = f'''
.bub {{ animation: rise linear infinite; }}
@keyframes rise {{ to {{ transform: translateY(-110%); }} }}
.tw {{ animation: tw ease-in-out infinite; }}
@keyframes tw {{ 0%,100% {{ opacity: .15; }} 50% {{ opacity: 1; }} }}
.swimR {{ animation: swimR linear infinite; }} .swimL {{ animation: swimL linear infinite; }}
@keyframes swimR {{ from {{ transform: translateX(-220px); }} to {{ transform: translateX(1420px); }} }}
@keyframes swimL {{ from {{ transform: translateX(1420px); }} to {{ transform: translateX(-220px); }} }}
.tail {{ transform-box: fill-box; transform-origin: right center; animation: wag .45s ease-in-out infinite alternate; }}
@keyframes wag {{ from {{ transform: scaleY(.55) skewY(-12deg); }} to {{ transform: scaleY(1.1) skewY(12deg); }} }}
.jel {{ animation: jel ease-in-out infinite alternate; }}
@keyframes jel {{ from {{ transform: translate(-14px, 16px); }} to {{ transform: translate(14px, -18px); }} }}
.beat {{ transform-box: fill-box; transform-origin: center bottom; animation: beat 1.9s ease-in-out infinite; }}
@keyframes beat {{ 50% {{ transform: scale(1.12, .84); }} }}
.tent {{ transform-box: fill-box; transform-origin: top center; animation: tent 1.9s ease-in-out infinite alternate; }}
@keyframes tent {{ from {{ transform: skewX(-9deg) scaleY(.92); }} to {{ transform: skewX(9deg) scaleY(1.08); }} }}
{RM}'''

# ---------- 1. surface ----------
W, H = 1200, 500
rays = "".join(f'<polygon class="ray" style="animation-delay:-{i*1.3:.1f}s" points="{80+i*170},-10 {80+i*170+60+(i%3)*40},-10 {80+i*170-170},{H} {80+i*170-300},{H}" fill="url(#ray)"/>' for i in range(7))
surface = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="scuba3198: Mumukshu D.C, Nepal. Small, sharp tools: browser extensions, Windows utilities and NEPSE trading helpers.">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b7a96"/><stop offset=".55" stop-color="#07425f"/><stop offset="1" stop-color="#042a44"/></linearGradient>
<linearGradient id="ray" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c8fff6" stop-opacity=".28"/><stop offset="1" stop-color="#c8fff6" stop-opacity="0"/></linearGradient>
<filter id="rip" x="-5%" y="-15%" width="110%" height="130%"><feTurbulence type="fractalNoise" baseFrequency="0.012 0.03" numOctaves="2" seed="4" result="n"><animate attributeName="baseFrequency" dur="9s" values="0.012 0.03;0.022 0.055;0.012 0.03" repeatCount="indefinite"/></feTurbulence><feDisplacementMap in="SourceGraphic" in2="n" scale="11"/></filter>
<clipPath id="c"><rect width="{W}" height="{H}"/></clipPath>
</defs>
<style>
.ray {{ animation: ray 6s ease-in-out infinite alternate; }}
@keyframes ray {{ from {{ opacity: .35; transform: translateX(-24px); }} to {{ opacity: 1; transform: translateX(24px); }} }}
.ping {{ transform-box: fill-box; transform-origin: center; animation: ping 3.2s ease-out infinite; }}
@keyframes ping {{ from {{ transform: scale(1); opacity: .9; }} to {{ transform: scale(3.2); opacity: 0; }} }}
.title {{ font: 800 168px {SANS}; letter-spacing: -8px; animation: plunge 1.3s cubic-bezier(.2,1.3,.3,1) backwards, bob 4s ease-in-out 1.3s infinite; }}
@keyframes plunge {{ from {{ opacity: 0; transform: translateY(-150px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes bob {{ 50% {{ transform: translateY(-7px); }} }}
.in {{ animation: up .9s cubic-bezier(.2,.8,.2,1) backwards; }}
@keyframes up {{ from {{ opacity: 0; transform: translateY(26px); }} to {{ opacity: 1; transform: none; }} }}
.mono {{ font: 500 17px {MONO}; letter-spacing: 2.5px; }}
.num {{ font: 800 58px {SANS}; }}
.cue {{ animation: cue 1.8s ease-in-out infinite; }}
@keyframes cue {{ 50% {{ transform: translateY(7px); opacity: .5; }} }}
{COMMON}
</style>
<g clip-path="url(#c)">
<rect width="{W}" height="{H}" fill="url(#bg)"/>
{rays}
{school(9, 120, '#bff6ee', 26, 4, 1)}
{school(8, 330, '#ffd9a0', 34, 20, -1, .9)}
{bubbles(34, W, H)}
<g class="in" style="animation-delay:.1s">
<circle class="ping" cx="78" cy="70" r="16" fill="none" stroke="#5cf2e0" stroke-width="1.5"/>
<circle class="ping" style="animation-delay:-1.6s" cx="78" cy="70" r="16" fill="none" stroke="#5cf2e0" stroke-width="1.5"/>
<circle cx="78" cy="70" r="9" fill="#5cf2e0"/>
<text x="118" y="66" fill="#fff" style="font: 700 26px {SANS}">Mumukshu D.C</text>
<text x="118" y="90" fill="#d3f1f2" class="mono" style="font-size:14px">NEPAL · STATUS: FOCUSING</text>
</g>
<g filter="url(#rip)"><text class="title" x="56" y="250" fill="#eafafa">scuba<tspan fill="none" stroke="#eafafa" stroke-width="3">3198</tspan></text></g>
<text class="in" style="animation-delay:.7s; font: 400 27px {SANS}" fill="#eafafa"><tspan x="62" y="304">I build small, sharp tools: browser extensions, Windows utilities</tspan><tspan x="62" dy="36">and trading helpers for </tspan><tspan fill="#ffb84a" font-weight="700">NEPSE</tspan>.</text>
<line x1="62" y1="372" x2="1138" y2="372" stroke="#fff" stroke-opacity=".3"/>
<g class="in" style="animation-delay:1s" fill="#eafafa">
{STATS}
</g>
<g class="cue"><text x="1138" y="480" text-anchor="end" class="mono" style="font-size:13px" fill="#eafafa">DESCEND ↓</text></g>
</g>
</svg>'''
open('assets/surface.svg', 'w').write(surface)

# ---------- 2. languages ----------
H = 330
langs = LANGS
x, segs, legend = 62, [], []
total_w, gap = 1076, 3
unit = (total_w - gap * (len(langs) - 1)) / N_LANGED
for i, (n, c, col) in enumerate(langs):
    w = unit * c
    segs.append(f'<rect class="seg" style="animation-delay:{.2+i*.12:.2f}s" x="{x:.1f}" y="118" width="{w:.1f}" height="54" fill="{col}"/>')
    x += w + gap
    lx = 62 + i * (total_w / max(7, len(langs)))
    legend.append(f'<g class="in" style="animation-delay:{.9+i*.1:.1f}s"><circle class="tw" style="animation-duration:3s;animation-delay:-{i*.4:.1f}s" cx="{lx+7:.0f}" cy="216" r="7" fill="{col}"/><text x="{lx+24:.0f}" y="222" fill="#eafafa" style="font: 700 19px {SANS}">{n}</text><text x="{lx:.0f}" y="262" fill="{col}" style="font: 500 30px {MONO}">{c:02d}</text></g>')
languages = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{LANG_ARIA}">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#042a44"/><stop offset="1" stop-color="#03182b"/></linearGradient>
<linearGradient id="sh" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<clipPath id="c"><rect width="{W}" height="{H}"/></clipPath>
<clipPath id="bar"><rect x="62" y="118" width="{total_w}" height="54" rx="9"/></clipPath>
</defs>
<style>
.seg {{ transform-box: fill-box; transform-origin: left center; animation: grow 1.1s cubic-bezier(.2,.8,.2,1) backwards; }}
@keyframes grow {{ from {{ transform: scaleX(0); }} }}
.sheen {{ animation: sheen 4s ease-in-out infinite; }}
@keyframes sheen {{ 0%,45% {{ transform: translateX(-200px); }} 100% {{ transform: translateX(1300px); }} }}
.in {{ animation: up .9s cubic-bezier(.2,.8,.2,1) backwards; }}
@keyframes up {{ from {{ opacity: 0; transform: translateY(22px); }} to {{ opacity: 1; transform: none; }} }}
.mono {{ font: 500 14px {MONO}; letter-spacing: 2.5px; }}
{COMMON}
</style>
<g clip-path="url(#c)">
<rect width="{W}" height="{H}" fill="url(#bg)"/>
{plankton(40, W, H)}
{school(10, 60, '#a9c8ff', 30, 11, -1, .85)}
{bubbles(12, W, H, .3)}
{jelly(1085, 250, '#5cf2e0', .9, 6, 2)}
<text x="62" y="52" class="mono in" fill="#5cf2e0">SUNLIGHT ZONE  <tspan fill="#9dbfc6">0 – 200 M</tspan></text>
<text x="62" y="94" class="in" style="animation-delay:.1s; font: 800 36px {SANS}; letter-spacing:-1px" fill="#eafafa">{LANG_HEAD}</text>
<g clip-path="url(#bar)">{"".join(segs)}<rect class="sheen" x="0" y="118" width="160" height="54" fill="url(#sh)"/></g>
{"".join(legend)}
<text x="62" y="304" class="mono" style="font-size:12px" fill="#9dbfc6">PRIMARY LANGUAGE OF EACH OF {N_LANGED} PUBLIC REPOS · UPDATED AUTOMATICALLY</text>
</g>
</svg>'''
open('assets/languages.svg', 'w').write(languages)

# ---------- 3. abyss ----------
H = 380
def orb(cx, col, label, sub, icon, delay):
    return f'''<g class="in" style="animation-delay:{delay}s"><circle class="spin" cx="{cx}" cy="150" r="52" fill="none" stroke="{col}" stroke-dasharray="4 6"/>
<circle class="pulse" cx="{cx}" cy="150" r="40" fill="url(#o{col[1:]})"/>
<g transform="translate({cx-20} 130)" fill="none" stroke="#02131c" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">{icon}</g>
<text x="{cx}" y="236" text-anchor="middle" fill="#eafafa" style="font: 700 19px {SANS}">{label}</text>
<text x="{cx}" y="260" text-anchor="middle" fill="#9dbfc6" style="font: 500 12px {MONO}; letter-spacing:2px">{sub}</text></g>'''
def top_orb(i, r):
    name = r['n'] if len(r['n']) <= 22 else r['n'][:21] + '…'
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 'S'}"
    number = f'<text x="20" y="31" text-anchor="middle" fill="#02131c" stroke="none" style="font: 800 30px {SANS}">{r["s"] + r["fk"]}</text>'
    return orb(200 + i * 270, ['#5cf2e0', '#ffb84a', '#ff6478'][i], xml(name), f"{plural(r['s'], 'STAR')} · {plural(r['fk'], 'FORK')}", number, .2 + i * .2)


orbs = ''.join(top_orb(i, r) for i, r in enumerate(TOP))
grads = "".join(f'<radialGradient id="o{c[1:]}" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#fff"/><stop offset=".25" stop-color="{c}"/><stop offset="1" stop-color="{c}" stop-opacity=".15"/></radialGradient>' for c in ['#5cf2e0', '#ffb84a', '#ff6478'])
teeth = "M127 6 " + " ".join(f"L{127-i*11} {6+(22 if i%2 else 4)+i*1.5:.1f}" for i in range(1, 10))
abyss = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{xml(ABYSS_ARIA)}">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#03182b"/><stop offset=".6" stop-color="#020b16"/><stop offset="1" stop-color="#01060d"/></linearGradient>
<radialGradient id="lure"><stop offset="0" stop-color="#ffbe5a" stop-opacity=".7"/><stop offset="1" stop-color="#ffbe5a" stop-opacity="0"/></radialGradient>
{grads}
<clipPath id="c"><rect width="{W}" height="{H}"/></clipPath>
</defs>
<style>
.spin {{ transform-box: fill-box; transform-origin: center; animation: spin 16s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.pulse {{ transform-box: fill-box; transform-origin: center; animation: pulse 3.2s ease-in-out infinite; }}
@keyframes pulse {{ 50% {{ transform: scale(1.1); }} }}
.angler {{ animation: patrol 30s linear infinite; }}
@keyframes patrol {{ from {{ transform: translateX(1500px); }} to {{ transform: translateX(-420px); }} }}
.hover {{ animation: hov 3.4s ease-in-out infinite alternate; }}
@keyframes hov {{ from {{ transform: translateY(-10px); }} to {{ transform: translateY(12px); }} }}
.flick {{ animation: flick 1.7s steps(1,end) infinite; }}
@keyframes flick {{ 0%,100% {{ opacity: 1; }} 42% {{ opacity: .45; }} 47% {{ opacity: 1; }} 71% {{ opacity: .6; }} 76% {{ opacity: 1; }} }}
.atail {{ transform-box: fill-box; transform-origin: right center; animation: wag 1.1s ease-in-out infinite alternate; }}
.in {{ animation: up .9s cubic-bezier(.2,.8,.2,1) backwards; }}
@keyframes up {{ from {{ opacity: 0; transform: translateY(22px); }} to {{ opacity: 1; transform: none; }} }}
.mono {{ font: 500 14px {MONO}; letter-spacing: 2.5px; }}
.cta {{ animation: glow 2.2s ease-in-out infinite; }}
@keyframes glow {{ 50% {{ opacity: .55; }} }}
.sonar {{ transform-box: fill-box; transform-origin: center; animation: sonar 2.6s ease-out infinite; }}
@keyframes sonar {{ from {{ transform: scale(.4); opacity: .9; }} to {{ transform: scale(1.5); opacity: 0; }} }}
{COMMON}
</style>
<g clip-path="url(#c)">
<rect width="{W}" height="{H}" fill="url(#bg)"/>
{plankton(70, W, H)}
<g class="angler"><g transform="translate(0 205) scale(-1 1)"><g class="hover">
<circle class="flick" cx="150" cy="-124" r="150" fill="url(#lure)"/>
<g fill="#01070e" stroke="#ffbe5a" stroke-opacity=".55" stroke-width="1.6">
<path class="atail" d="M-110 0 L-195 -58 L-195 58 Z"/>
<ellipse rx="130" ry="94"/>
<path d="M-13 -91 L-58 -133 L-78 -73" fill="none"/>
</g>
<path d="{teeth}" fill="none" stroke="#e6f6f7" stroke-opacity=".85" stroke-width="1.6"/>
<circle cx="65" cy="-32" r="9" fill="#ffb84a"/>
<path d="M45 -83 Q78 -176 150 -124" fill="none" stroke="#ffbe5a" stroke-opacity=".7" stroke-width="1.6"/>
<circle class="flick" cx="150" cy="-124" r="6" fill="#fff3d0"/>
</g></g></g>
{jelly(1010, 120, '#b693ff', .8, 8, 3)}
{jelly(1120, 250, '#ff6478', .6, 6, 1)}
{school(8, 300, '#9ff5ea', 28, 9, 1, .8)}
<text x="62" y="50" class="mono in" fill="#5cf2e0">ABYSSAL ZONE  <tspan fill="#9dbfc6">4,000 – 6,000 M · MOST STARRED + FORKED</tspan></text>
{orbs}
<g class="in" style="animation-delay:.9s">
<circle class="sonar" cx="86" cy="326" r="20" fill="none" stroke="#5cf2e0" stroke-width="1.5"/>
<circle cx="86" cy="326" r="6" fill="#5cf2e0"/>
<g class="cta"><text x="118" y="334" fill="#eafafa" style="font: 800 26px {SANS}; letter-spacing:-.5px">Dive the full interactive version →</text></g>
<text x="1138" y="332" text-anchor="end" class="mono" style="font-size:12px" fill="#9dbfc6">CHALLENGER DEEP · 10,935 M</text>
</g>
</g>
</svg>'''
open('assets/abyss.svg', 'w').write(abyss)
