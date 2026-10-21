"""Point d'entree ``python -m app.backtest`` : voir ``app.backtest.cli``.

La logique vit dans un module importable : sous Windows, les processus du
rejeu parallele ne savent pas retrouver une fonction definie dans ``__main__``.
"""

from app.backtest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
