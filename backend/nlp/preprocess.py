import re

URL = re.compile(r"https?://\S+")
WS = re.compile(r"\s+")
CODEBLOCK = re.compile(r"```.*?```", flags=re.S)

def clean_text(s: str) -> str:
    if not s: return ""
    s = CODEBLOCK.sub(" ", s)
    s = URL.sub(" ", s)
    s = s.replace("\n", " ")
    s = WS.sub(" ", s)
    return s.strip()[:4000]  # safety clip
