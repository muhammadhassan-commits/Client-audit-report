# Parkinsans

The Wellows brand typeface, the only typeface the design system allows.

Two subsets of the variable font, taken from Google Fonts:

| File | Subset | Why it is here |
|---|---|---|
| `pk-latin.woff2` | latin | Core Latin |
| `pk-latinext.woff2` | latin-ext | Turkish, Polish, Czech and the rest of extended Latin. A Turkish client's report shows `ş` and `ğ` correctly only with this. |

`build_report.py` inlines both as base64 at build time, so the report keeps the
brand typeface and still opens with no network access. Replacing the font means
replacing these two files; nothing else needs to change.

Licence: SIL Open Font License 1.1, which permits embedding.
