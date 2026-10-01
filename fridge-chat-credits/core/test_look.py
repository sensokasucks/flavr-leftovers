"""Sanity checks for look sanitizer — run: python3 core/test_look.py"""

from look import ALLOWED_MOTIONS, merge_look, sanitize_look


def check(name, cond):
    if not cond:
        raise SystemExit(f"FAIL: {name}")
    print("ok", name)


def main():
    check("matrix stays matrix", sanitize_look({"motion": "matrix"})["motion"] == "matrix")
    check("teletype alias", sanitize_look({"motion": "teletype"})["motion"] == "typewriter")
    check("unknown falls back to crawl", sanitize_look({"motion": "simple"})["motion"] == "crawl")
    check("typewriter unit kept", sanitize_look({"motion": "typewriter", "typewriter_unit": "card"})["typewriter_unit"] == "card")
    check("matrix density clamped", sanitize_look({"matrix_density": 9})["matrix_density"] == 2.2)
    check("cps kept", sanitize_look({"motion": "typewriter", "typewriter_cps": 28})["typewriter_cps"] == 28)
    merged = merge_look({"motion": "crawl", "title_color": "#fff"}, {"motion": "matrix", "matrix_density": 1.4})
    check("merge keeps matrix", merged["motion"] == "matrix" and merged["matrix_density"] == 1.4)
    check("all editor motions allowed", {"matrix", "typewriter", "starwars", "ticker"}.issubset(set(ALLOWED_MOTIONS)))
    print("look sanitizer ok")


if __name__ == "__main__":
    main()
