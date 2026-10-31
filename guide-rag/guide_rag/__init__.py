"""guide-rag: a documentary chatbot over a public guide, built brick by brick.

Brick 1 (``guide_rag.parsing`` + ``guide_rag.storage``) turns the site into tables.
The other bricks read those tables, never the HTML again.
"""

__version__ = "0.1.0"

# Stamped on every table and every answer, so a trace says which code made it.
PIPELINE_VERSION = f"guide-rag/{__version__}"
