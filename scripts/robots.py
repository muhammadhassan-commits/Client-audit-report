"""robots.txt parser that follows RFC 9309 / Google's matching rules.

- Group selection: the group whose user-agent token is the longest match for the
  crawler's product token wins; fall back to '*'. Groups naming the same token
  are merged.
- Rule matching: the longest matching path wins; on a tie, Allow wins.
- Wildcards: '*' matches any sequence, '$' anchors the end.
Python's urllib.robotparser uses first-match semantics, which gives wrong
verdicts on many real files, so it is not used.
"""
import re
from urllib.parse import urlparse, unquote


class Robots:
    def __init__(self, text: str):
        self.groups = {}  # token -> list[(allow: bool, pattern: str)]
        self.sitemaps = []
        self.other = []  # non-standard lines (Content-Signal, Crawl-delay, ...)
        self.parse_warnings = []
        self._parse(text or "")

    def _parse(self, text):
        agents, rules_started = [], False
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                self.parse_warnings.append(f"line {n}: no colon: {raw.strip()[:80]}")
                continue
            key, val = [x.strip() for x in line.split(":", 1)]
            k = key.lower()
            if k == "user-agent":
                if rules_started:
                    agents, rules_started = [], False
                tok = val.lower()
                agents.append(tok)
                self.groups.setdefault(tok, [])
            elif k in ("allow", "disallow"):
                if not agents:
                    self.parse_warnings.append(f"line {n}: rule before any user-agent")
                    continue
                rules_started = True
                if k == "disallow" and val == "":
                    continue  # empty disallow = allow all
                for a in agents:
                    self.groups[a].append((k == "allow", val))
            elif k == "sitemap":
                self.sitemaps.append(val)
            else:
                self.other.append({"line": n, "key": key, "value": val, "agents": list(agents)})

    def group_for(self, token: str):
        token = token.lower()
        best = None
        for g in self.groups:
            if g == "*":
                continue
            if token.startswith(g) or g == token:
                if best is None or len(g) > len(best):
                    best = g
        if best is not None:
            return best
        return "*" if "*" in self.groups else None

    @staticmethod
    def _to_regex(pattern: str):
        esc = ""
        for ch in pattern:
            if ch == "*":
                esc += ".*"
            elif ch == "$":
                esc += "$"
            else:
                esc += re.escape(ch)
        return re.compile("^" + esc)

    def verdict(self, token: str, url: str):
        """Return (allowed: bool, group: str|None, matched_rule: str|None)."""
        g = self.group_for(token)
        if g is None:
            return True, None, None
        p = urlparse(url)
        path = unquote(p.path or "/") + (("?" + p.query) if p.query else "")
        best_len, best_allow, best_rule = -1, True, None
        for allow, pat in self.groups[g]:
            if pat == "":
                continue
            if self._to_regex(unquote(pat)).match(path):
                plen = len(pat)
                if plen > best_len or (plen == best_len and allow and not best_allow):
                    best_len, best_allow = plen, allow
                    best_rule = ("Allow: " if allow else "Disallow: ") + pat
        return best_allow, g, best_rule


if __name__ == "__main__":
    sample = """User-agent: *
Disallow: /private/
Allow: /private/public$

User-agent: GPTBot
Disallow: /

User-agent: googlebot
Disallow: /tmp
Allow: /tmp/ok
"""
    r = Robots(sample)
    for tok, url in [("GPTBot", "https://x.com/"), ("Googlebot", "https://x.com/tmp/a"),
                     ("Googlebot", "https://x.com/tmp/ok/1"), ("ClaudeBot", "https://x.com/private/public"),
                     ("ClaudeBot", "https://x.com/private/a"), ("Googlebot-Image", "https://x.com/tmp")]:
        print(tok, url, r.verdict(tok, url))
