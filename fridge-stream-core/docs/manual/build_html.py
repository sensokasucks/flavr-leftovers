# Rebuilds the one-file HTML (pictures embedded) from a Markdown file. Run inside docs/manual:
#   python build_html.py            (MANUAL.md -> MANUAL.html)
#   python build_html.py ROOM_GUIDE.md
import re, base64, io, sys, markdown
from PIL import Image
src=sys.argv[1] if len(sys.argv) > 1 else 'MANUAL.md'; md=open(src,encoding='utf-8').read()
body=markdown.markdown(md, extensions=['tables','toc','fenced_code'])
def emb(m):
    path=m.group(1)
    im=Image.open(path).convert('RGB'); b=io.BytesIO(); im.save(b,'JPEG',quality=86,optimize=True)
    return 'src="data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()+'"'
body=re.sub(r'src="(images/[^"]+)"',emb,body)
# captions from alt text
body=re.sub(r'<p><img alt="([^"]*)" (src="[^"]+") /></p>', r'<figure><img alt="\1" \2 loading="lazy"><figcaption>\1</figcaption></figure>', body)
css='''
:root{--bg:#f7f6f3;--fg:#1d1d22;--muted:#5d5d68;--card:#ffffff;--line:#dedbd4;--accent:#b4341f;--code:#efece6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#131317;--fg:#e9e7e2;--muted:#a3a1ab;--card:#1c1c22;--line:#2f2f37;--accent:#ff8a65;--code:#25252c}}
:root[data-theme="dark"]{--bg:#131317;--fg:#e9e7e2;--muted:#a3a1ab;--card:#1c1c22;--line:#2f2f37;--accent:#ff8a65;--code:#25252c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 "Segoe UI",system-ui,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:2rem;line-height:1.2;margin:2.2em 0 .6em;color:var(--accent)}
main>h1:first-child{margin-top:.4em;color:var(--fg)}
h2{font-size:1.45rem;margin:2em 0 .5em;padding-top:.4em;border-top:1px solid var(--line)}
h3{font-size:1.1rem;margin:1.6em 0 .4em}
a{color:var(--accent)}
code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:.92em;word-break:break-word}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:.95em;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
th{background:var(--code)}
figure{margin:1.4em 0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
figure img{display:block;max-width:100%;height:auto;margin:0 auto;border-radius:6px}
figcaption{color:var(--muted);font-size:.9em;margin-top:6px;text-align:center}
hr{border:0;border-top:2px solid var(--line);margin:3em 0}
'''
title='Stream Core Manual'
html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head><body><main>{body}</main></body></html>'''
open(src.rsplit('.',1)[0]+'.html','w',encoding='utf-8').write(html)
print(len(html)//1024,'KB')
