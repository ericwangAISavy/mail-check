"""Opt-in durable collection and browser invalidation support.

Redis is imported only when a broker connection is first used, so ordinary
application startup remains available without the optional realtime services.
"""
