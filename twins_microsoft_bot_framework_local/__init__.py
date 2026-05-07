"""Local SQLite-backed host for the Microsoft Bot Framework twin.

Run with::

    python -m twins_microsoft_bot_framework_local

Or via gunicorn::

    gunicorn 'twins_microsoft_bot_framework_local.host:create_local_app()'
"""
