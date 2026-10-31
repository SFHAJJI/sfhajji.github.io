"""Brick 1: document parsing.

Pipeline: ``fetch`` (the site, politely, into ``raw/``) → ``documents`` (what counts as one
document, with the site's JS data rendered as HTML) → ``blocks`` (HTML → lines, headings,
table rows, links) → ``tables`` (pandas frames of SPEC §1).
"""
