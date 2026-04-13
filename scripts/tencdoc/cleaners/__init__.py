"""Cleaner pipeline stages.

Each cleaner is a callable taking a ``CleanerContext`` and returning the
(possibly modified) markdown text. Cleaners are registered in ``pipeline.py``
in the order they should run.
"""
