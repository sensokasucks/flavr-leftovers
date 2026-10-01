"""Chat command / emote cheat sheets -> PNGs (rendered with headless Chromium)."""
import asyncio, html
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path("/mnt/user-data/outputs/chat_guide")
OUT.mkdir(parents=True, exist_ok=True)
E = html.escape

CSS = r"""
@font-face { font-family: Pop; src: url(file:///usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf); font-weight: 400; }
@font-face { font-family: Pop; src: url(file:///usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf); font-weight: 500; }
@font-face { font-family: Pop; src: url(file:///usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf); font-weight: 700; }
:root { --bg:#0d1017; --card:#161b26; --line:#262e3f; --ink:#eef1f7; --muted:#8d97ab;
        --kick:#53fc18; --twitch:#a970ff; --yt:#ff4e45; --live:#53fc18; --soon:#ffb347; --acc:#53fc18; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--ink); font-family:Pop, "Noto Color Emoji", sans-serif; width:1600px; }
.sheet { padding:48px 56px 40px; background:
   radial-gradient(1200px 500px at 0% 0%, color-mix(in srgb, var(--acc) 12%, transparent), transparent 60%), var(--bg); }
.kicker { font-size:15px; letter-spacing:.32em; text-transform:uppercase; color:var(--acc); font-weight:700; }
h1 { font-size:54px; line-height:1.05; font-weight:700; margin:6px 0 10px; }
.sub { color:var(--muted); font-size:19px; max-width:1180px; line-height:1.5; }
.legend { display:flex; gap:18px; flex-wrap:wrap; margin:22px 0 26px; align-items:center; font-size:15px; color:var(--muted); }
.chip { display:inline-flex; align-items:center; gap:7px; border-radius:999px; padding:4px 12px 4px 10px; font-size:14px; font-weight:500;
        border:1px solid var(--line); background:#0f131b; color:var(--ink); white-space:nowrap; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
.k { background:var(--kick); } .t { background:var(--twitch); } .y { background:var(--yt); }
.badge { font-size:12px; font-weight:700; letter-spacing:.12em; padding:4px 10px; border-radius:6px; white-space:nowrap; }
.live { color:#0b0d10; background:var(--live); } .soon { color:#1a1206; background:var(--soon); }
.tag { font-size:12.5px; font-weight:500; color:var(--muted); border:1px dashed #3a4459; padding:3px 9px; border-radius:6px; white-space:nowrap; }
.section { margin-top:30px; }
.section h2 { font-size:24px; font-weight:700; margin-bottom:12px; display:flex; align-items:center; gap:12px; }
.section h2 small { font-size:15px; color:var(--muted); font-weight:400; }
.rows { background:var(--card); border:1px solid var(--line); border-radius:16px; overflow:hidden; }
.row { display:grid; grid-template-columns: 64px 420px 1fr 230px; gap:0 22px; align-items:center; padding:16px 24px;
       border-top:1px solid var(--line); }
.row:first-child { border-top:0; }
.ico { font-size:34px; text-align:center; line-height:1; }
.cmd { font-family:"DejaVu Sans Mono", monospace; font-size:21px; font-weight:700; color:var(--acc); line-height:1.35; }
.cmd .arg { color:#9fb0cc; font-weight:400; }
.what { font-size:18px; line-height:1.45; }
.what .ex { color:var(--muted); font-size:15px; display:block; margin-top:3px; }
.meta { display:flex; flex-direction:column; gap:7px; align-items:flex-end; }
.meta .line { display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
.foot { margin-top:30px; display:flex; gap:26px; flex-wrap:wrap; color:var(--muted); font-size:15px; line-height:1.5;
        border-top:1px solid var(--line); padding-top:18px; }
.foot b { color:var(--ink); font-weight:500; }
/* emote mood cards */
.moods { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
.mood { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px 22px; }
.mood-h { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
.mood-h .ico { font-size:40px; }
.mood-h .name { font-size:25px; font-weight:700; }
.mood .eff { color:var(--acc); font-size:17px; font-weight:500; margin:2px 0 12px; }
.plat { display:grid; grid-template-columns:104px 1fr; gap:6px 12px; align-items:start; margin-top:8px; font-size:15.5px; }
.plat .p { display:flex; align-items:center; gap:7px; font-weight:700; font-size:14px; letter-spacing:.04em; padding-top:3px; }
.names { display:flex; flex-wrap:wrap; gap:6px; }
.em { font-family:"DejaVu Sans Mono", monospace; font-size:14.5px; background:#0f131b; border:1px solid var(--line); border-radius:7px; padding:3px 8px; }
.em.x { color:var(--muted); border-style:dashed; }
.none { color:#5a6479; }
.note { background:#121826; border:1px solid var(--line); border-left:4px solid var(--acc); border-radius:10px; padding:14px 18px;
        font-size:17px; line-height:1.5; margin-top:18px; }
"""

PLAT = {"k": ("Kick", "k"), "t": ("Twitch", "t"), "y": ("YouTube", "y")}

def chips(plats):
    if plats == "all":
        return '<span class="chip"><span class="dot k"></span><span class="dot t"></span><span class="dot y"></span>All platforms</span>'
    return "".join(f'<span class="chip"><span class="dot {PLAT[p][1]}"></span>{PLAT[p][0]}</span>' for p in plats)

def cmd_html(c):
    # <arg>, [optional] and @name are arguments (brackets may hold spaces)
    import re
    out = []
    for tok in re.findall(r"<[^>]*>|\[[^\]]*\]|\S+", c):
        if tok[:1] in "<[" or tok.startswith("@") or tok == "|":
            out.append(f'<span class="arg">{E(tok)}</span>')
        else:
            out.append(E(tok))
    return " ".join(out)


def row(ico, cmd, what, ex="", status="live", plats="all", tags=()):
    badge = '<span class="badge live">LIVE</span>' if status == "live" else '<span class="badge soon">PLANNED</span>'
    tg = "".join(f'<span class="tag">{E(t)}</span>' for t in tags)
    exh = f'<span class="ex">{ex}</span>' if ex else ""
    return (f'<div class="row"><div class="ico">{ico}</div><div class="cmd">{cmd_html(cmd)}</div>'
            f'<div class="what">{what}{exh}</div>'
            f'<div class="meta"><div class="line">{badge}</div><div class="line">{chips(plats)}</div>'
            f'<div class="line">{tg}</div></div></div>')

def section(title, sub, rows):
    return f'<div class="section"><h2>{title} <small>{sub}</small></h2><div class="rows">{"".join(rows)}</div></div>'

LEGEND = ('<div class="legend">'
          '<span class="badge live">LIVE</span> works now'
          '<span class="chip"><span class="dot k"></span><span class="dot t"></span><span class="dot y"></span>All platforms</span> same on Kick, Twitch, YouTube'
          '<span class="tag">costs points</span> uses your stream points'
          '</div>')

FOOT = ('<div class="foot"><span><b>Answers show on the reply screen</b> above the main screen (Stream Core can\'t post into chat).</span>'
        '<span><b>Commands start with !</b> and work the same on every platform.</span>'
        '<span><b>Cooldowns apply.</b> Spamming won\'t make things happen faster.</span></div>')

def page(kicker, title, sub, body, acc="#53fc18"):
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body style="--acc:{acc}"><div class="sheet" id="sheet"><div class="kicker">{E(kicker)}</div>'
            f'<h1>{title}</h1><div class="sub">{sub}</div>{body}</div></body></html>')

sheets = {}

# ── 1. Reactions + crowd moments ───────────────────────────────
sheets["1_reactions"] = page("Stream chat guide · 1 of 5", "Throw things &amp; make noise",
    "Send an emoji or a command and it happens in the room: on the stage, the screen, a presenter, or someone in the audience.",
    LEGEND + section("Reactions", "aim with a word or an @name", [
        row("🍅", "!tomato [target] [x5]", "Throw a tomato. It arcs from your seat and splats.",
            "!tomato · !tomato screen · !tomato @bob · !tomato presenter2 x3", "live", tags=("may cost points",)),
        row("🌹", "!rose | !roses [target]", "Roses drift down on the stage or on someone.", "Typing 🌹 or 💐 does it too", "live"),
        row("🎉", "!confetti", "A confetti burst over the stage.", "Typing 🎉 does it too", "live"),
        row("🕺", "!wiggle | !dance", "Your silhouette in the audience dances.", "", "live"),
        row("🎯", "!targets", "Lists what you can aim at in this room.", "stage, screen, chat, presenters, podiums, @names", "live"),
        row("🛡️", "!nothrow  ·  !throwok", "Stop people aiming at you, or allow it again.", "", "live"),
    ]) + section("Crowd moments", "the more people join, the bigger it gets", [
        row("📣", "!cheer  ·  !boo", "Tug of war. A meter swings with every cheer or boo; the winning side gets a reveal.", "", "live"),
        row("🚀", "!launch", "Group countdown. Enough people type it within a minute and the room goes big: lights down, spotlight, fireworks.", "", "live"),
        row("🔥", "(just chat)", "Hype meter. Builds as more different people chat; each level sets off a cheer, confetti or a stadium wave.", "", "live"),
    ]) + FOOT, "#ff6b4a")

# ── 2. Emote combos ────────────────────────────────────────────
def mood(ico, name, eff, k, t, y, emo):
    def names(lst):
        if not lst:
            return '<span class="none">—</span>'
        out = []
        for n in lst:
            x = n.endswith("*")
            out.append(f'<span class="em{" x" if x else ""}">{E(n.rstrip("*"))}</span>')
        return "".join(out)
    return (f'<div class="mood"><div class="mood-h"><div class="ico">{ico}</div><div class="name">{E(name)}</div></div>'
            f'<div class="eff">{E(eff)}</div><div class="plat">'
            f'<div class="p"><span class="dot k"></span>KICK</div><div class="names">{names(k)}</div>'
            f'<div class="p"><span class="dot t"></span>TWITCH</div><div class="names">{names(t)}</div>'
            f'<div class="p"><span class="dot y"></span>YOUTUBE</div><div class="names">{names(y)}</div>'
            f'<div class="p">EMOJI</div><div class="names">{" ".join(f"<span style=font-size:22px>{e}</span>" for e in emo)}</div>'
            f'</div></div>')

moods = [
    mood("😂", "Laugh", "The emote floats up from every laugher; the crowd wiggles",
         ["KEKW", "LULW", "HaHaa", "KEKLEO"], ["LUL", "KEKW*", "OMEGALUL*"], ["face-purple-smiling-tears", "face-fuchsia-tongue-out"], ["😂", "🤣"]),
    mood("🤩", "Hype", "Confetti, and the audience stands and cheers",
         ["PogU", "OOOO", "GIGACHAD", "AURAPULSE"], ["PogChamp", "Kreygasm"], ["face-blue-star-eyes", "rocket-red-countdown-liftoff", "trophy-yellow-smiling"], ["🔥", "😮", "🚀"]),
    mood("👏", "Clap", "The applause meter fills",
         ["Clap", "HYPERCLAP", "PeepoClap"], ["Clap*"], ["hands-yellow-heart-red"], ["👏", "🙌"]),
    mood("❤️", "Love", "Hearts float up from each seat",
         ["catKISS"], ["<3", "bleedPurple"], ["face-red-heart-shape", "eyes-pink-heart-shape", "face-blue-heart-eyes", "virtualhug"], ["❤️", "💜", "😍"]),
    mood("😢", "Sad", "Tears drift down over the stage",
         ["Sadge", "Prayge"], ["BibleThump", "NotLikeThis"], ["face-purple-crying", "face-pink-tears", "eyes-purple-crying"], ["😢", "😭"]),
    mood("🪩", "Dance", "The whole audience grooves",
         ["vibePls", "ratJAM", "catblobDance", "duckPls", "DanceDance", "GnomeDisco", "ODAJAM", "peepoDJ", "EDMusiC"], ["catJAM*"], ["person-pink-swaying-hair", "face-turquoise-music-note"], ["💃", "🕺", "🎶"]),
    mood("😱", "Shock / huh?", "A small camera shake",
         ["kkHuh", "modCheck", "SUSSY", "WeirdChamp"], ["WutFace", "monkaS*"], ["face-fuchsia-wide-eyes", "face-blue-question-mark", "face-orange-biting-nails"], ["😱", "🤨", "❓"]),
    mood("😴", "Sleepy", "The room lights dim for a moment",
         [], ["ResidentSleeper"], ["face-blue-droopy-eyes", "face-turquoise-drinking-coffee"], ["😴", "💤"]),
    mood("👋", "Bye / GG", "A stadium wave rolls across the seats",
         ["KEKBye", "EZ"], ["HeyGuys", "GG"], ["hand-pink-waving", "text-green-game-over"], ["👋", "🏆"]),
]
special = section("Special emotes", "one-off effects", [
    row("💥", "FLASHBANG", "The room lights flash white.", "", "live", "k"),
    row("🚨", "POLICE", "Red and blue lights flash around the room.", "", "live", "k"),
    row("🔥", "ThisIsFine", "The stage catches (harmless, cartoon) fire.", "", "live", "k"),
    row("🧱", "DonoWall", "A big shout bubble over the sender.", "", "live", "k"),
])
sheets["2_emotes"] = page("Stream chat guide · 2 of 5", "Emote combos",
    "Emotes don't fire one by one. When <b>3 or more people</b> use emotes from the same group within <b>10 seconds</b>, the whole room reacts, and it's bigger the more people join in.",
    '<div class="legend"><span class="badge live">LIVE</span> everything on this page'
    '<span class="em">Name</span> global emote'
    '<span class="em x">Name</span> BetterTTV / FrankerFaceZ / 7TV (if the channel has it)'
    '<span class="chip">YouTube names are typed like <span class="em" style="margin-left:6px">:face-blue-star-eyes:</span></span></div>'
    f'<div class="moods">{"".join(moods)}</div>' + special +
    '<div class="note">Channel emotes (subs, members) can be added to any group. Emote lists follow each platform\'s global set, which can change.</div>',
    "#ffd23f")

# ── 3. Your seat ───────────────────────────────────────────────
sheets["3_seat"] = page("Stream chat guide · 3 of 5", "Your seat in the audience",
    "Chat and you get a seat in the virtual audience: a silhouette in your colour, with your picture on Kick and YouTube and your messages in a speech bubble.",
    LEGEND + section("Seat", "", [
        row("💺", "(just chat)", "Get a seat. Stay active to keep it; after a while quiet you give it up.", "Front row fills first when the streamer turns that on", "live"),
        row("🎟️", "!seat front | back", "Move to a free seat at the front or the back. Front-row seats cost points (refunded if no seat is free).", "", "live", tags=("front costs points",)),
        row("🔁", "!swap @name", "Offer to trade seats. They type !swap to accept.", "", "live"),
    ]) + section("Do something", "", [
        row("🪧", "!sign <text>", "Hold up a sign over your head for 20 seconds.", "!sign GO TEAM", "live", tags=("may cost points",)),
        row("😴", "!sleep  ·  !snack  ·  !phone", "Doze off (Zzz), grab popcorn, or light up your phone.", "", "live"),
        row("🙌", "!highfive @name", "You both jump and high-five across the room.", "", "live"),
    ]) + FOOT, "#6fc3ff")

# ── 4. Points & games ─────────────────────────────────────────
sheets["4_points"] = page("Stream chat guide · 4 of 5", "Points &amp; games",
    "You earn points by chatting. Spend them on reactions, seats and games. Points are the stream's own, so they work on every platform.",
    LEGEND + section("Points", "", [
        row("💰", "!points | !balance | !pts", "Your points balance.", "", "live"),
        row("📅", "!claim", "Free points once per stream. Also counts your attendance.", "", "live"),
    ]) + section("Games", "", [
        row("🔮", "!predict <option> <points>", "Bet on something the streamer sets up (&ldquo;will there be a twist?&rdquo;). Winners split the pot.", "!predict yes 50 · !predict 2 100", "live", tags=("costs points",)),
        row("⚔️", "!duel @name <points>", "Coin-flip duel. They answer !accept or !decline. The loser gets a tomato to the face.", "", "live", tags=("costs points",)),
        row("🎰", "!slots <points>", "Spin the slots. Capped, with a cooldown.", "", "live", tags=("costs points",)),
        row("💼", "!heist <points>  ·  !join", "Start or join a heist. After 60 seconds the crew's fate plays out on the reply screen.", "", "live", tags=("costs points",)),
        row("❓", "!answer <guess>", "Trivia on the reply screen. First right answer wins points and a spotlight on their seat.", "", "live"),
    ]) + FOOT, "#c9a0ff")

# ── 5. Watch-along & regulars ────────────────────────────────
sheets["5_watch"] = page("Stream chat guide · 5 of 5", "Watch along &amp; be a regular",
    "Help pick what's on, rate it, mark the best moments, and build up your streak.",
    LEGEND + section("What's on", "", [
        row("🗳️", "!1  ·  !2  ·  !3", "Vote in a poll (mods start one with !poll Question? | A | B). Live bars show on screen.", "", "live"),
        row("⭐", "!rate <1-10>", "Rate what we just watched. The average goes up on screen and into the end credits.", "!rate 9", "live"),
        row("📺", "!request <link or title>", "Suggest what to watch next. <b>!bump</b> spends points to move yours up; <b>!queue</b> shows what's next.", "", "live", tags=("points to bump",)),
        row("📌", "!clip | !moment", "Mark this moment so it's easy to find later.", "", "live"),
    ]) + section("Regulars", "", [
        row("🔥", "!streak", "How many streams in a row you've been here. Titles at 5 (Regular), 10 (Die-hard) and 25 (Legend).", "", "live"),
        row("🎬", "!credits", "How many people are in tonight's end credits.", "", "live"),
        row("🏷️", '!credit "name" "job"', "Mods give someone a job title in the movie-style end credits.", '!credit "bob" "Chief Snack Officer"', "live", tags=("mods",)),
        row("🎖️", "(earned)", "Titles for regulars on your name tag and in the credits.", "", "live"),
        row("❔", "!help | !commands", "Lists the commands that are on right now.", "", "live"),
    ]) + FOOT, "#53fc18")

# ── 6. For mods ────────────────────────────────────────────────
sheets["6_mods"] = page("Stream chat guide · for mods", "Running the games",
    "Mods and the streamer start these from chat (or from Stream Core → Chat games). Everyone sees the live board on screen.",
    '<div class="legend"><span class="badge live">LIVE</span> works now'
    '<span class="tag">mods</span> mods and admins only</div>' + section("Polls", "", [
        row("🗳️", "!poll Question? | A | B | C", "Opens a poll; chat votes !1 !2 !3. Add <b>| 90s</b> at the end to close it on a timer.",
            "!poll Next up? | Movie | Cartoons | 60s", "live", tags=("mods",)),
        row("🛑", "!poll end", "Closes it and announces the winner.", "", "live", tags=("mods",)),
    ]) + section("Predictions", "", [
        row("🔮", "!predict open Question? | A | B", "Opens betting (no options = Yes / No).", "!predict open Will there be a twist? | yes | no", "live", tags=("mods",)),
        row("🔒", "!predict lock", "Stops new bets.", "", "live", tags=("mods",)),
        row("🏁", "!predict win <option>", "Pays out: winners split the whole pot.", "!predict win yes", "live", tags=("mods",)),
        row("↩️", "!predict cancel", "Refunds everyone.", "", "live", tags=("mods",)),
    ]) + section("Trivia + ratings", "", [
        row("❓", "!trivia  ·  !trivia stop", "Asks a question (first right !answer wins) or skips it.", "", "live", tags=("mods",)),
        row("⭐", "!rate open <title>  ·  !rate close", "Names what chat is rating, or closes voting early. Chat's first !rate also opens it.", "", "live", tags=("mods",)),
    ]) + section("Stage", "", [
        row("🎭", "!curtain open | close | reveal", "The red curtain in front of the screen. <b>reveal</b> = lights down, drum roll, curtain sweeps open. Just <b>!curtain</b> toggles it.", "", "live", tags=("mods",)),
    ]) + FOOT, "#ffb347")

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        for name, doc in sheets.items():
            f = OUT / f"{name}.html"
            f.write_text(doc, encoding="utf-8")
            await pg.goto(f.as_uri())
            await pg.wait_for_timeout(400)
            el = await pg.query_selector("#sheet")
            await el.screenshot(path=str(OUT / f"chat_guide_{name}.png"))
            f.unlink()
            print(name, (await el.bounding_box())["height"])
        await b.close()
asyncio.run(main())
