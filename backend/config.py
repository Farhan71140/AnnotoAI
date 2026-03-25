import os

_groq_env = os.environ.get("GROQ_KEYS", "")
if _groq_env:
    GROQ_KEYS = [k.strip() for k in _groq_env.split(",") if k.strip()]
else:
    GROQ_KEYS = []

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
