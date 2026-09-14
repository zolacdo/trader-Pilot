"""Acces aux donnees, regroupe par domaine."""

from app.repositories import channel_repo, journal_repo, settings_repo, signal_repo, trade_repo

__all__ = ["channel_repo", "journal_repo", "settings_repo", "signal_repo", "trade_repo"]
