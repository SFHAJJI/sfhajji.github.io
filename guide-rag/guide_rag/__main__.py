"""`python -m guide_rag` runs the CLI; the module path matters: `-m guide_rag.cli` would import guide_rag.cli twice."""
from guide_rag.cli import main

raise SystemExit(main())
