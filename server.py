import sys
import os
import json
import tempfile

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--quiet"])
    import requests

import http.server

try:
    from auth import (login, logout, verify_token, record_action,
                     add_user, remove_user, toggle_user,
                     reset_password, get_dashboard_data, clear_all_sessions)
    AUTH_ENABLED = True
    print("[*] Auth system loaded")
    clear_all_sessions()  # Wipe all sessions on every restart — forces re-login
except ImportError:
    AUTH_ENABLED = False
    print("[!] auth.py not found - running without auth")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", 7842))

GROQ_URL          = "https://api.groq.com/openai/v1/chat/completions"
GROQ_WHISPER_URL  = "https://api.groq.com/openai/v1/audio/transcriptions"
GEMINI_URL        = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
ASSEMBLYAI_UPLOAD = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_SUBMIT = "https://api.assemblyai.com/v2/transcript"

try:
    from config import GROQ_KEYS, GEMINI_KEY
    ASSEMBLYAI_KEYS = getattr(__import__('config'), 'ASSEMBLYAI_KEYS', [])
    GEMINI_KEYS     = getattr(__import__('config'), 'GEMINI_KEYS', [GEMINI_KEY] if GEMINI_KEY else [])
    print(f"[*] Loaded {len(GROQ_KEYS)} Groq key(s) from config.py")
except ImportError:
    # ── Cloud deployment (Leapcell or any other host) ────────────────────────
    # Reads keys from environment variables.
    # Supported names:
    #   ASSEMBLYAI_KEY        — single key
    #   ASSEMBLYAI_KEY_1 ..   — multiple keys
    #   GEMINI_KEY            — single key
    #   GEMINI_KEY_1 ..       — multiple keys
    #   GROQ_KEY_1 ..         — optional fallback keys
    GROQ_KEYS = []
    for _i in range(1, 20):
        _k = os.environ.get(f"GROQ_KEY_{_i}", "").strip()
        if _k:
            GROQ_KEYS.append(_k)

    # AssemblyAI
    ASSEMBLYAI_KEYS = []
    _single_aai = os.environ.get("ASSEMBLYAI_KEY", "").strip()
    if _single_aai:
        ASSEMBLYAI_KEYS.append(_single_aai)
    for _i in range(1, 10):
        _k = os.environ.get(f"ASSEMBLYAI_KEY_{_i}", "").strip()
        if _k and _k not in ASSEMBLYAI_KEYS:
            ASSEMBLYAI_KEYS.append(_k)

    # Gemini
    GEMINI_KEYS = []
    _single_gem = os.environ.get("GEMINI_KEY", "").strip()
    if _single_gem:
        GEMINI_KEYS.append(_single_gem)
    for _i in range(1, 10):
        _k = os.environ.get(f"GEMINI_KEY_{_i}", "").strip()
        if _k and _k not in GEMINI_KEYS:
            GEMINI_KEYS.append(_k)
    GEMINI_KEY = GEMINI_KEYS[0] if GEMINI_KEYS else ""

    # ── Startup summary ───────────────────────────────────────────────────────
    if ASSEMBLYAI_KEYS:
        print(f"[*] Loaded {len(ASSEMBLYAI_KEYS)} AssemblyAI key(s) — primary transcription")
    else:
        print("[!] WARNING: No AssemblyAI keys found!")
        print("[!]   Set env var ASSEMBLYAI_KEY=your_key_here")
        if GROQ_KEYS:
            print(f"[!]   Falling back to Groq Whisper ({len(GROQ_KEYS)} key(s))")
        else:
            print("[!]   No Groq keys either — transcription will FAIL")

    if GEMINI_KEYS:
        print(f"[*] Loaded {len(GEMINI_KEYS)} Gemini key(s) — primary annotation")
    else:
        print("[!] WARNING: No Gemini keys found!")
        print("[!]   Set env var GEMINI_KEY=your_key_here")
        if GROQ_KEYS:
            print(f"[!]   Falling back to Groq LLM ({len(GROQ_KEYS)} key(s))")
        else:
            print("[!]   No Groq keys either — annotation will FAIL")

    if GROQ_KEYS:
        print(f"[*] Loaded {len(GROQ_KEYS)} Groq key(s) — fallback only")

# ── AssemblyAI key rotation ───────────────────────────────────────────────────
_assemblyai_key_index = 0

def _get_next_assemblyai_key():
    global _assemblyai_key_index
    if not ASSEMBLYAI_KEYS:
        return None
    key = ASSEMBLYAI_KEYS[_assemblyai_key_index % len(ASSEMBLYAI_KEYS)]
    _assemblyai_key_index = (_assemblyai_key_index + 1) % len(ASSEMBLYAI_KEYS)
    return key

# ── Gemini key rotation ───────────────────────────────────────────────────────
_gemini_key_index = 0

def _get_next_gemini_key():
    global _gemini_key_index
    if not GEMINI_KEYS:
        return None
    key = GEMINI_KEYS[_gemini_key_index % len(GEMINI_KEYS)]
    _gemini_key_index = (_gemini_key_index + 1) % len(GEMINI_KEYS)
    return key

_groq_key_index = 0
_groq_exhausted = set()
_last_reset_day = None

def _get_next_groq_key():
    global _groq_key_index, _groq_exhausted, _last_reset_day
    import datetime
    today = datetime.date.today().isoformat()
    if _last_reset_day != today:
        _groq_exhausted = set()
        _groq_key_index = 0
        _last_reset_day = today
    available = [k for i, k in enumerate(GROQ_KEYS) if i not in _groq_exhausted]
    if not available:
        return None
    key = available[_groq_key_index % len(available)]
    _groq_key_index = (_groq_key_index + 1) % len(available)
    return key

def _mark_key_exhausted(key):
    global _groq_exhausted
    try:
        idx = GROQ_KEYS.index(key)
        _groq_exhausted.add(idx)
        print(f"[!] Groq Key #{idx+1} exhausted.")
    except ValueError:
        pass


SYSTEM_PROMPT = """Speech annotation AI - DesicrewAI Spoken English Assessment (Jan 2026).

YOU ARE AN ANNOTATOR, NOT A TRANSLATOR. NEVER CONVERT ENGLISH TO HINDI.

GOLDEN RULE: Transcribe the WHOLE audio EXACTLY as heard. Every word, sound, and extra utterance must be included — even if not in the reference text. If it is a real English word pronounced recognisably (including accent variations), KEEP IN ENGLISH.

ALWAYS KEEP IN ENGLISH: a, an, the, I, you, he, she, it, we, they, me, him, her, us, them, my, his, its, our, their, is, are, was, were, be, been, have, has, had, do, does, did, will, would, shall, should, may, might, can, could, must, and, or, but, so, if, as, at, by, for, from, in, into, of, on, out, to, up, with, about, after, before, through, this, that, these, those, here, there, what, which, who, when, where, why, how, today, take, safety, piston, use, post, allow, keep, your, hands, go, get, give, come, make, know, think, see, look, want, find, tell, ask, say, said, went, came, told, work, help, good, great, new, old, long, time, day, year, people, way, man, woman, child, world, life, hand, place, home, water, name, word

CORE PRINCIPLES:
1. Transcribe the WHOLE audio as heard — include ALL words and sounds even if not in the reference text.
2. Accent variations are acceptable if the word remains recognisable as English. UK, US, and Indian English are all valid.
   - Stress variations like "de-vel-op-ment" vs "DE-vel-op-ment" are acceptable.
   - Pronunciation differences like "de-TER-mine" vs "de-ter-MINE" are acceptable.
   - "Education" as "E-du-kay-shun" or "E-joo-kay-shun" is acceptable, but NOT "E-zu-ka-shon".
   - If pronunciation ambiguity exists, use US/UK/Indian Google pronunciations as tie-breakers.
3. If pronunciation matches the reference text (standard or acceptable accent variant), write the word EXACTLY as in the reference.
4. If pronunciation does NOT match, transcribe as heard (verbatim).
5. Timestamps: mark start and end of EACH word in HH:MM:SS:MS format. Pauses are separate entries. Each word fits snugly between its timestamps.

3 DECISIONS:
D1 KEEP ENGLISH (90%+ of words): Real English word + recognisable pronunciation (including accent variants).
D2 SUBSTITUTE ENGLISH (rare): Mispronunciation sounds like a DIFFERENT valid English word.
   - "colon" pronounced as "kuh-lur" → colour
   - "man" pronounced as "main" → main
   - "house" pronounced as "horse" → horse
D3 DEVANAGARI (only these cases):
   a) Proper noun (person, place, entity name) — ALWAYS Devanagari.
   b) Mispronunciation that sounds like NO valid English word — write phonetically in Devanagari.
   c) Non-English / unrecognisable sound.
   d) Special cases: filler sounds, letter-spelling of non-English words, stretched/elongated words.

RULES:

A) PROPER NOUNS — always Devanagari regardless of pronunciation:
   - Person names: Karthik=कार्तिक, Priya=प्रिया
   - Place names: England=इंग्लैंड, Mumbai=मुंबई
   - Entity/brand names also in Devanagari.

B) ACCENT & PRONUNCIATION VARIATIONS — keep English if word is still recognisable:
   - "leisure", "schedule" — if correctly read with any valid English accent, write as in reference.
   - If incorrectly read but becomes another valid English word, write that valid English word (D2).
   - If incorrectly read and NOT a valid English word, write phonetically in Devanagari (D3).
   Examples: pigeon pronounced as "pid-jun" → पिडजन | literacy → लिट सरी | blak → ब्लक् | shei-p → शेइप्

C) INSERTED / EXTRA WORDS — transcribe everything spoken even if not in reference:
   - If valid English word → keep English.
   - If not a valid English word → write phonetically in Devanagari.

D) LETTER-BY-LETTER SPELLING — use <LN></LN> tag per letter:
   - If the spelled-out letters form a recognisable valid English word, keep that word in English (no LN tags needed).
   - If not, write each letter sound in Devanagari inside individual LN tags.
   - balloon spelled b-a-l-l-o-o-n → <LN>बी</LN> <LN>ए</LN> <LN>एल</LN> <LN>एल</LN> <LN>ओ</LN> <LN>ओ</LN> <LN>एन</LN>
   - pan spelled p-a-n → <LN>पी</LN> <LN>ये</LN> <LN>एन</LN>
   - If individual letter pronunciations are non-standard, transcribe as heard in Devanagari inside LN tags.
   LETTER NAME DEVANAGARI MAP: A=ए, B=बी, C=सी, D=डी, E=ई, F=एफ, G=जी, H=एच, I=आई, J=जे, K=के, L=एल, M=एम, N=एन, O=ओ, P=पी, Q=क्यू, R=आर, S=एस, T=टी, U=यू, V=वी, W=डब्लू, X=एक्स, Y=वाई, Z=ज़ेड

E) SUB-LEXICAL PAUSES (intra-word pauses) — evaluate each part independently:
   - If each part is a valid English word or valid pronunciation of one → keep in English (e.g., "pro long" → pro long).
   - If not → write each part phonetically in Devanagari (e.g., "कम प्यूट").

F) SUB-LEXICAL STRETCH (elongated/stretched syllables) — write full word in Devanagari + add only ONE extra vowel or consonant to indicate elongation:
   - "cooooming" → कूमिंग (one extra vowel ू added)
   - Do not add more than one extra character for elongation.

G) FALSE STARTS AND REPETITIONS — transcribe verbatim exactly as heard:
   - f-i-r-e fire → <LN>एफ</LN> <LN>आई</LN> <LN>आर</LN> <LN>ई</LN> fire
   - c-c-clown → <LN>सी</LN> <LN>सी</LN> clown

H) PUNCTUATION WITHIN WORDS — include exactly as heard:
   - you're → you're | dog's → dog's | catch-up → catch-up

I) TIMESTAMPS — use HH:MM:SS:MS format. Each word has its own snug start and end time. Pauses and silences are separate annotation entries with their own exact timestamps.

5 TAGS — ALL tags MUST have an opening AND closing tag. Tag EVERY word or word-part individually:

1. <MB></MB>: Completely unintelligible/indiscernible speech. Use EMPTY tags: <MB></MB>.
   - Use for any portion that cannot be transcribed in English or Devanagari.

2. <NOISE></NOISE>: Background ambient noise or chatter.
   - Pure noise with no speech → EMPTY tags: <NOISE></NOISE>
   - Speech heard WITH background noise → word INSIDE tags: <NOISE>camel</NOISE>
   - Child speech audible through noise → transcribe inside NOISE tags.

3. <LN></LN>: Letter-by-letter spelling. ONE tag per letter. Content in Devanagari per map above.
   - If a word is split across parts, tag each part separately.

4. <FIL></FIL>: ONLY genuine hesitation/filler sounds. Do NOT tag the article 'a' or pronoun 'I' as filler.
   - uh / uhh → <FIL>अ</FIL>
   - um / umm → <FIL>अम</FIL>
   - hmm / hm → <FIL>हम</FIL>
   - aaah / aah → <FIL>आ</FIL>
   - eeh / eh → <FIL>ए</FIL>
   - ooh → <FIL>ऊ</FIL>
   - Any other drawn-out hesitation sound → transcribe phonetically in Devanagari inside FIL tags.
   - Filler WITH background noise → apply BOTH FIL and NOISE tags together.

5. <SIL></SIL>: Silence longer than 2 seconds ONLY. Each silence is its OWN separate annotation entry with EXACT start and end timestamps. Use empty tags: <SIL></SIL>.

MULTIPLE TAGS: Multiple tags can and must be applied together when needed. Every tag must have both opening and closing forms. If a word is split, each part must be tagged separately.

DEVANAGARI PHONEME MAP:
Vowels: a=अ, aa=आ, i=इ, ee/ii=ई, u=उ, oo/uu=ऊ, e=ए, ai=ऐ, o=ओ, au=औ
Consonants: k=क, kh=ख, g=ग, gh=घ, ch=च, chh=छ, j=ज, jh=झ, t=त, th=थ, d=द, dh=ध, n=न, T=ट, Th=ठ, D=ड, Dh=ढ, N=ण, p=प, ph=फ, b=ब, bh=भ, m=म, r=र, l=ल, v=व, sh=श, Sh=ष, s=स, h=ह, y=य, R=ड़, L=ळ
Abrupt consonant end (no following vowel): use halant (्). Example: blak=ब्लक्
Nasal sound: use anusvara (ं). Example: ang=अंग

SELF-CHECK every single word before outputting:
1. Is it a genuine hesitation sound (uh, um, hmm, aaah, eeh, ooh etc.) and NOT the article 'a' or pronoun 'I'? → FIL tag.
2. Is it completely unintelligible with no discernible sound? → Empty MB tag.
3. Is there background noise with no speech? → Empty NOISE tag.
4. Is there background noise BUT speech can be heard? → Word inside NOISE tags.
5. Is there silence longer than 2 seconds? → SIL tag as its own annotation entry with exact timestamps.
6. Are individual letters being spelled out? → LN tag per letter in Devanagari. If spelled letters form a valid English word, keep English (no LN tags).
7. Is it a proper noun (person name, place name, entity name)? → Devanagari ALWAYS.
8. Are syllables being stretched/elongated? → Full word in Devanagari + ONLY ONE extra vowel or consonant for elongation.
9. Is it a false start, stutter, or repetition? → Transcribe verbatim exactly as heard.
10. Is there an intra-word (sub-lexical) pause? → Evaluate each part independently by rules above.
11. IS IT A REAL ENGLISH WORD WITH RECOGNISABLE PRONUNCIATION (including accent variants)? → KEEP IN ENGLISH. THIS IS 90% OF ALL WORDS. DO NOT CONVERT TO DEVANAGARI.
12. Is the mispronunciation recognisable as a DIFFERENT valid English word? → Write that English word (D2).
13. Nothing above matched? → Write phonetically in Devanagari (D3).

OVERALL PRINCIPLE: Always transcribe everything exactly as heard. Use English if the word is valid and recognisable. Use Devanagari if not. Apply all tags correctly. Handle pauses, silences, noise, fillers, stretching, and pronunciation variations precisely per rules above.

Step 11 covers 90% of words. YOU ARE AN ANNOTATOR NOT A TRANSLATOR."""



class AnnotoHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]

        if path == '/' or path == '/index.html':
            if AUTH_ENABLED:
                self.serve_file('login.html')
            else:
                self.serve_file('annotation_tool.html')

        elif path == '/login':
            self.serve_file('login.html')

        elif path == '/tool':
            self.serve_file('annotation_tool.html')

        elif path == '/view':
            self.serve_file('view_annotations.html')

        elif path == '/admin':
            self.serve_file('admin.html')

        elif path == '/check':
            self.send_json({
                "status": "ok",
                "assemblyai_keys": len(ASSEMBLYAI_KEYS),
                "gemini_keys": len(GEMINI_KEYS),
                "groq_keys": len(GROQ_KEYS),
            })

        # ── NEW: debug endpoint to diagnose key loading on Leapcell ──────────
        elif path == '/debug-keys':
            self.send_json({
                "assemblyai_keys_loaded": len(ASSEMBLYAI_KEYS),
                "assemblyai_key_1_set":   bool(os.environ.get("ASSEMBLYAI_KEY_1", "").strip()),
                "assemblyai_key_set":     bool(os.environ.get("ASSEMBLYAI_KEY", "").strip()),
                "gemini_keys_loaded":     len(GEMINI_KEYS),
                "gemini_key_1_set":       bool(os.environ.get("GEMINI_KEY_1", "").strip()),
                "gemini_key_set":         bool(os.environ.get("GEMINI_KEY", "").strip()),
                "groq_keys_loaded":       len(GROQ_KEYS),
                "leapcell_env":           bool(os.environ.get("LEAPCELL") or os.environ.get("LEAPCELL_APP_NAME")),
                "config_py_used":         False,
            })

        elif path == '/test-keys':
            self.handle_test_keys()

        elif path == '/admin/dashboard':
            self.handle_admin_dashboard()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split('?')[0]
        ct   = self.headers.get('Content-Type', '')
        if path == '/transcribe' and 'multipart' in ct:
            self.handle_transcribe_upload()
        elif path == '/transcribe-url':
            self.handle_transcribe_url()
        elif path == '/annotate':
            self.handle_annotate()
        elif path == '/login':
            self.handle_login()
        elif path == '/logout':
            self.handle_logout()
        elif path == '/verify-token':
            self.handle_verify_token()
        elif path == '/set-key':
            length = int(self.headers.get('Content-Length', 0))
            self.rfile.read(length)
            self.send_json({"status": "ok"})
        elif path == '/admin/add-user':
            self.handle_admin_action('add_user')
        elif path == '/admin/remove-user':
            self.handle_admin_action('remove_user')
        elif path == '/admin/toggle-user':
            self.handle_admin_action('toggle_user')
        elif path == '/admin/reset-password':
            self.handle_admin_action('reset_password')
        else:
            self.send_response(404)
            self.end_headers()

    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length))

    def get_token(self):
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:]
        return ''

    def _get_token_from_request(self):
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:]
        if '?' in self.path:
            query = self.path.split('?', 1)[1]
            for part in query.split('&'):
                if part.startswith('token='):
                    return part[6:]
        return ''

    def redirect_to_login(self):
        self.send_response(302)
        self.send_header('Location', '/login')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def serve_file(self, filename):
        path = os.path.join(BASE_DIR, filename)
        if not os.path.exists(path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f'{filename} not found'.encode())
            return
        with open(path, 'rb') as f:
            content = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def handle_login(self):
        try:
            data   = self.read_json()
            result = login(data.get('username', ''), data.get('password', ''))
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)})

    def handle_logout(self):
        try:
            data  = self.read_json()
            token = data.get('token', '') or self.get_token()
            if AUTH_ENABLED: logout(token)
        except Exception:
            pass
        self.send_json({"status": "ok"})

    def handle_verify_token(self):
        try:
            data  = self.read_json()
            token = data.get('token', '')
            if not AUTH_ENABLED:
                self.send_json({"valid": True, "role": "admin"})
                return
            user = verify_token(token)
            if user:
                self.send_json({"valid": True, "role": user.get('role', 'student'), "name": user.get('name', '')})
            else:
                self.send_json({"valid": False})
        except Exception:
            self.send_json({"valid": False})

    def handle_admin_dashboard(self):
        if AUTH_ENABLED:
            token = self.get_token()
            user  = verify_token(token)
            if not user or user.get('role') != 'admin':
                self.send_json({"error": "Unauthorized"}, 401)
                return
        self.send_json(get_dashboard_data())

    def handle_admin_action(self, action):
        if AUTH_ENABLED:
            token = self.get_token()
            user  = verify_token(token)
            if not user or user.get('role') != 'admin':
                self.send_json({"error": "Unauthorized"}, 401)
                return
        try:
            data = self.read_json()
        except Exception:
            self.send_json({"error": "Invalid request"}); return
        if action == 'add_user':
            result = add_user(data.get('username', ''), data.get('password', ''),
                              data.get('name', ''), data.get('role', 'student'))
        elif action == 'remove_user':
            result = remove_user(data.get('username', ''))
        elif action == 'toggle_user':
            result = toggle_user(data.get('username', ''), data.get('active', True))
        elif action == 'reset_password':
            result = reset_password(data.get('username', ''), data.get('new_password', ''))
        else:
            result = {"error": "Unknown action"}
        self.send_json(result)

    def handle_test_keys(self):
        results = []
        for i, key in enumerate(GROQ_KEYS):
            masked = key[:8] + "..." + key[-4:]
            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": "Say OK"}],
                          "max_tokens": 5},
                    timeout=15
                )
                if resp.status_code == 200:   status = "✅ WORKING"
                elif resp.status_code == 429: status = "⚠️ RATE LIMITED"
                elif resp.status_code == 401: status = "❌ INVALID KEY"
                else:                         status = f"❌ ERROR {resp.status_code}"
            except Exception as e:
                status = f"❌ FAILED: {str(e)[:50]}"
            results.append({"key_number": i+1, "key_masked": masked, "status": status})
        working = sum(1 for r in results if "WORKING" in r["status"])
        self.send_json({
            "summary": {"total_keys": len(GROQ_KEYS), "working": working,
                        "daily_capacity": f"{working*100000:,} tokens/day"},
            "keys": results
        })

    def handle_transcribe_upload(self):
        import email.parser, email.policy
        print("[*] Receiving audio file...")
        try:
            content_type = self.headers['Content-Type']
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            msg_bytes = b'Content-Type: ' + content_type.encode() + b'\r\n\r\n' + body
            msg = email.parser.BytesParser(policy=email.policy.compat32).parsebytes(msg_bytes)
            file_data = None
            filename = 'audio.wav'
            for part in msg.walk():
                cd = part.get('Content-Disposition', '')
                if 'name="audio"' in cd:
                    fn = part.get_filename()
                    if fn: filename = fn
                    file_data = part.get_payload(decode=True)
                    break
            if file_data is None:
                self.send_json({"error": "No audio file found in request"}); return
            ext = os.path.splitext(filename)[1] or '.wav'
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=tempfile.gettempdir())
            tmp.write(file_data)
            tmp.close()
            result = run_transcribe(tmp.name, filename)
            try: os.unlink(tmp.name)
            except: pass
            if AUTH_ENABLED: record_action(self.get_token(), 'transcription')
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)})

    def handle_transcribe_url(self):
        try:
            body = self.read_json()
            url  = body.get('url', '')
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                self.send_json({"error": f"Could not download: {resp.status_code}"}); return
            ext = '.mp3' if 'mp3' in url else '.wav'
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=tempfile.gettempdir())
            for chunk in resp.iter_content(chunk_size=8192): tmp.write(chunk)
            tmp.close()
            filename = url.split('/')[-1].split('?')[0] or 'audio.wav'
            result   = run_transcribe(tmp.name, filename)
            try: os.unlink(tmp.name)
            except: pass
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)})

    def handle_annotate(self):
        try:
            payload = self.read_json()
            result  = call_groq_annotate(payload)
            if AUTH_ENABLED and result.get('status') == 'ok':
                record_action(self.get_token(), 'annotation')
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)})


def run_assemblyai_whisper(audio_path, original_filename):
    """Transcription via AssemblyAI with key rotation — no IP restrictions."""
    import time
    key = _get_next_assemblyai_key()
    if not key:
        return {"error": "No AssemblyAI keys available. Set ASSEMBLYAI_KEY env var in Leapcell."}
    print(f"[*] AssemblyAI transcribing: {original_filename}")

    # Step 1: Upload audio file
    try:
        with open(audio_path, "rb") as f:
            up = requests.post(
                ASSEMBLYAI_UPLOAD,
                headers={"authorization": key, "content-type": "application/octet-stream"},
                data=f, timeout=120
            )
        if up.status_code != 200:
            return {"error": f"AssemblyAI upload failed {up.status_code}: {up.text[:200]}"}
        upload_url = up.json()["upload_url"]
    except Exception as e:
        return {"error": f"AssemblyAI upload error: {str(e)}"}

    # Step 2: Submit transcription job
    try:
        sub = requests.post(
            ASSEMBLYAI_SUBMIT,
            headers={"authorization": key, "content-type": "application/json"},
            json={"audio_url": upload_url, "format_text": False},
            timeout=30
        )
        if sub.status_code != 200:
            return {"error": f"AssemblyAI submit failed {sub.status_code}: {sub.text[:200]}"}
        job_id = sub.json()["id"]
    except Exception as e:
        return {"error": f"AssemblyAI submit error: {str(e)}"}

    # Step 3: Poll until complete (max 4 minutes)
    poll_url = f"{ASSEMBLYAI_SUBMIT}/{job_id}"
    data = {}
    for _ in range(120):
        time.sleep(2)
        try:
            poll = requests.get(poll_url, headers={"authorization": key}, timeout=15)
            data = poll.json()
            status = data.get("status")
            if status == "completed":
                break
            elif status == "error":
                return {"error": f"AssemblyAI transcription error: {data.get('error', 'unknown')}"}
        except Exception as e:
            return {"error": f"AssemblyAI poll error: {str(e)}"}
    else:
        return {"error": "AssemblyAI transcription timed out"}

    # Step 4: Parse results with word-level timestamps
    full_transcript = data.get("text", "").strip()
    raw_words       = data.get("words", [])

    def fmt(ms):
        secs = max(0.0, float(ms) / 1000.0)
        h = int(secs // 3600); m = int((secs % 3600) // 60); s = int(secs % 60)
        us = int(round((secs - int(secs)) * 1_000_000))
        return f"{h}:{m:02d}:{s:02d}.{us:06d}"

    def classify(word):
        w = word.lower().strip(".,!?()")
        fillers = {'uh','uhh','uhhh','um','umm','ummm','ah','ahh','aah','aaah',
                   'hmm','hm','hmmm','eh','ehh','er','erm','haan','han','oh','ohh','mm','mmm'}
        if w in fillers: return 'LIKELY_FILLER'
        if any('ऀ' <= c <= 'ॿ' for c in word): return 'LIKELY_DEVANAGARI'
        if len(w) > 3 and sum(1 for c in w if c in 'aeiou') == 0: return 'LIKELY_MB'
        safe = {'the','a','an','i','in','on','at','to','of','is','was','are','were','and','or','but'}
        if word and word[0].isupper() and w not in safe: return 'LIKELY_PROPER_NOUN'
        return 'NORMAL'

    words = []
    for w in raw_words:
        word = w.get("text", "").strip()
        if not word: continue
        start_ms = float(w.get("start", 0))
        end_ms   = float(w.get("end",   0))
        words.append({"word": word, "start": fmt(start_ms), "end": fmt(end_ms),
                      "start_seconds": round(start_ms / 1000.0, 6),
                      "end_seconds":   round(end_ms   / 1000.0, 6),
                      "hint": classify(word), "is_english": True})

    silence_gaps = []
    for i in range(len(words) - 1):
        gap = words[i+1]["start_seconds"] - words[i]["end_seconds"]
        if gap > 2.0:
            silence_gaps.append({"after_word": words[i]["word"], "before_word": words[i+1]["word"],
                                 "gap_seconds": round(gap, 6), "sil_start": words[i]["end"],
                                 "sil_end": words[i+1]["start"]})
    leading_silence = None
    if words and words[0]["start_seconds"] > 2.0:
        leading_silence = {"gap_seconds": round(words[0]["start_seconds"], 6),
                           "sil_start": fmt(0), "sil_end": words[0]["start"], "type": "leading"}
        silence_gaps.insert(0, leading_silence)

    print(f"[*] AssemblyAI done! {len(words)} words")
    return {"status": "ok", "result": {
        "audio_file": original_filename, "full_transcript": full_transcript,
        "words": words, "silence_gaps": silence_gaps,
        "leading_silence": leading_silence, "sublex_pauses": [], "hint_summary": {}
    }}


def run_transcribe(audio_path, original_filename):
    """Router: AssemblyAI first (no restrictions), Groq Whisper as fallback."""
    if ASSEMBLYAI_KEYS:
        result = run_assemblyai_whisper(audio_path, original_filename)
        if result.get("status") == "ok":
            return result
        error_msg = result.get('error', 'unknown error')
        print(f"[!] AssemblyAI failed: {error_msg}")
        # Only fall back to Groq if we actually have Groq keys
        if not GROQ_KEYS:
            return {"error": f"Transcription failed: {error_msg}. No fallback keys available."}
        print(f"[!] Falling back to Groq Whisper ({len(GROQ_KEYS)} key(s))...")
    else:
        # No AssemblyAI keys at all
        if GROQ_KEYS:
            print("[!] No AssemblyAI keys — using Groq Whisper")
        else:
            return {"error": (
                "No transcription API keys found. "
                "Please set ASSEMBLYAI_KEY in your Leapcell environment variables."
            )}
    return run_groq_whisper(audio_path, original_filename)


def run_groq_whisper(audio_path, original_filename):
    print(f"[*] Groq Whisper transcribing: {original_filename}")
    key = _get_next_groq_key()
    if not key:
        return {"error": "No Groq API keys available. Set GROQ_KEY_1 or ASSEMBLYAI_KEY env vars."}
    file_size = os.path.getsize(audio_path)
    if file_size > 25 * 1024 * 1024:
        return {"error": "Audio too large. Max 25MB."}
    ext       = os.path.splitext(original_filename)[1].lower() or '.wav'
    mime_map  = {'.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.mp4': 'audio/mp4',
                 '.m4a': 'audio/mp4', '.ogg': 'audio/ogg', '.flac': 'audio/flac', '.webm': 'audio/webm'}
    mime_type = mime_map.get(ext, 'audio/wav')

    def do_request(k):
        with open(audio_path, 'rb') as f:
            return requests.post(
                GROQ_WHISPER_URL,
                headers={"Authorization": f"Bearer {k}"},
                files={"file": (original_filename, f, mime_type)},
                data={"model": "whisper-large-v3", "response_format": "verbose_json",
                      "timestamp_granularities[]": "word", "language": "en", "temperature": "0"},
                timeout=300
            )

    try:
        resp = do_request(key)
        if resp.status_code == 429:
            _mark_key_exhausted(key)
            key2 = _get_next_groq_key()
            if key2: resp = do_request(key2)
            else: return {"error": "All Groq keys rate limited."}
        if resp.status_code != 200:
            return {"error": f"Groq Whisper Error {resp.status_code}: {resp.text[:300]}"}
        result          = resp.json()
        full_transcript = result.get("text", "").strip()
        raw_words       = result.get("words", [])

        def fmt(secs):
            secs = max(0.0, float(secs))
            h = int(secs // 3600); m = int((secs % 3600) // 60); s = int(secs % 60)
            us = int(round((secs - int(secs)) * 1_000_000))
            return f"{h}:{m:02d}:{s:02d}.{us:06d}"

        def classify(word):
            w = word.lower().strip(".,!?()")
            fillers = {'uh','uhh','uhhh','um','umm','ummm','ah','ahh','aah','aaah',
                       'hmm','hm','hmmm','eh','ehh','er','erm','haan','han','oh','ohh','mm','mmm'}
            if w in fillers: return 'LIKELY_FILLER'
            if any('\u0900' <= c <= '\u097F' for c in word): return 'LIKELY_DEVANAGARI'
            if len(w) > 3 and sum(1 for c in w if c in 'aeiou') == 0: return 'LIKELY_MB'
            safe = {'the','a','an','i','in','on','at','to','of','is','was','are','were','and','or','but'}
            if word and word[0].isupper() and w not in safe: return 'LIKELY_PROPER_NOUN'
            return 'NORMAL'

        words = []
        for w in raw_words:
            word = w.get("word", "").strip()
            if not word: continue
            start = float(w.get("start", 0)); end = float(w.get("end", 0))
            words.append({"word": word, "start": fmt(start), "end": fmt(end),
                          "start_seconds": round(start, 6), "end_seconds": round(end, 6),
                          "hint": classify(word), "is_english": True})

        silence_gaps = []
        for i in range(len(words) - 1):
            gap = words[i+1]["start_seconds"] - words[i]["end_seconds"]
            if gap > 2.0:
                silence_gaps.append({"after_word": words[i]["word"], "before_word": words[i+1]["word"],
                                     "gap_seconds": round(gap, 6), "sil_start": words[i]["end"],
                                     "sil_end": words[i+1]["start"]})
        leading_silence = None
        if words and words[0]["start_seconds"] > 2.0:
            leading_silence = {"gap_seconds": round(words[0]["start_seconds"], 6),
                               "sil_start": fmt(0), "sil_end": words[0]["start"], "type": "leading"}
            silence_gaps.insert(0, leading_silence)

        print(f"[*] Groq Whisper done! {len(words)} words")
        return {"status": "ok", "result": {
            "audio_file": original_filename, "full_transcript": full_transcript,
            "words": words, "silence_gaps": silence_gaps,
            "leading_silence": leading_silence, "sublex_pauses": [], "hint_summary": {}
        }}
    except Exception as e:
        return {"error": f"Transcription failed: {str(e)}"}


MAX_WORDS_PER_CHUNK = 80
MAX_CHUNK_RETRIES   = 3
CHUNK_RETRY_DELAY   = 2


def _chunked_annotate(payload, chunk_size):
    import random, time
    words        = payload.get("words", [])
    all_annotations = []
    all_annotic     = []
    total_chunks    = -(-len(words) // chunk_size)

    for i in range(0, len(words), chunk_size):
        chunk        = words[i:i + chunk_size]
        chunk_num    = i // chunk_size + 1
        chunk_payload = dict(payload)
        chunk_payload["words"] = chunk

        chunk_start = chunk[0].get("start_seconds", 0)
        chunk_end   = chunk[-1].get("end_seconds", 9999999)

        def _sil_to_secs(s):
            t = s.get("sil_start", "")
            if not t:
                return s.get("gap_seconds", 0)
            try:
                p = str(t).split(":")
                return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
            except Exception:
                return 0.0

        chunk_payload["silence_gaps"] = [
            s for s in payload.get("silence_gaps", [])
            if chunk_start <= _sil_to_secs(s) <= chunk_end
        ]

        print(f"[*] Chunk {chunk_num}/{total_chunks}: words {i}–{i + len(chunk) - 1}")

        last_error = None
        for attempt in range(1, MAX_CHUNK_RETRIES + 1):
            result = call_groq_annotate(chunk_payload)
            if result.get("status") == "ok":
                last_error = None
                break
            last_error = result.get("error", "unknown error")
            if "exhausted" in last_error.lower() or "gemini" in last_error.lower():
                return result
            print(f"[!] Chunk {chunk_num} attempt {attempt} failed: {last_error} — retrying in {CHUNK_RETRY_DELAY}s")
            time.sleep(CHUNK_RETRY_DELAY)

        if last_error:
            print(f"[!] Chunk {chunk_num} failed after {MAX_CHUNK_RETRIES} attempts: {last_error}")
            return {"error": f"Chunk {chunk_num}/{total_chunks} failed: {last_error}"}

        res = result["result"]
        all_annotations.extend(res.get("annotations", []))
        all_annotic.extend(res.get("annotic_json", {}).get("annotations", []))
        print(f"[*] Chunk {chunk_num}/{total_chunks} done. Running total: {len(all_annotations)} annotations")

    merged = {
        "transcript":   " ".join(a.get("annotated", "") for a in all_annotations),
        "annotations":  all_annotations,
        "explanation":  f"Chunked annotation merged ({total_chunks} chunks).",
        "annotic_json": {
            "file_name":   payload.get("filename", "audio.wav"),
            "id":          __import__('random').randint(10000, 99999),
            "annotations": all_annotic,
        }
    }
    print(f"[*] All {total_chunks} chunks merged. Total annotations: {len(all_annotations)}")
    return {"status": "ok", "result": merged}


def call_groq_annotate(payload):
    ref          = payload.get("reference", "")
    words        = payload.get("words", [])
    transcript   = payload.get("transcript", "")
    filename     = payload.get("filename", "audio.wav")
    silence_gaps = payload.get("silence_gaps", [])

    if len(words) > MAX_WORDS_PER_CHUNK:
        print(f"[*] {len(words)} words exceeds limit — splitting into chunks of {MAX_WORDS_PER_CHUNK}")
        return _chunked_annotate(payload, MAX_WORDS_PER_CHUNK)

    words_fmt    = "\n".join([
        f'"{w["word"]}" [{w["start"]} -> {w["end"]}] HINT:{w.get("hint","NORMAL")}'
        for w in words
    ])

    def to_secs(t):
        try:
            p = t.split(":"); return int(p[0])*3600 + int(p[1])*60 + float(p[2])
        except: return 0

    if not silence_gaps:
        for i in range(len(words) - 1):
            gap = to_secs(words[i+1]["start"]) - to_secs(words[i]["end"])
            if gap > 2.0:
                silence_gaps.append({"after_word": words[i]["word"], "before_word": words[i+1]["word"],
                                     "gap_seconds": round(gap, 2), "sil_start": words[i]["end"],
                                     "sil_end": words[i+1]["start"]})

    silence_notes = "\n".join([
        f"[SIL] {s.get('gap_seconds',0)}s between '{s.get('after_word','')}' and '{s.get('before_word','')}' | START:{s.get('sil_start','')} END:{s.get('sil_end','')}"
        for s in silence_gaps
    ]) or "None"

    filler_words = [w["word"] for w in words if w.get("hint") == "LIKELY_FILLER"]
    proper_words = [w["word"] for w in words if w.get("hint") == "LIKELY_PROPER_NOUN"]
    devan_words  = [w["word"] for w in words if w.get("hint") == "LIKELY_DEVANAGARI"]
    mb_words     = [w["word"] for w in words if w.get("hint") == "LIKELY_MB"]

    hint_block = ""
    if filler_words: hint_block += f"FILLER SOUNDS detected (apply FIL tag): {', '.join(filler_words)}\n"
    if proper_words: hint_block += f"PROPER NOUNS detected (apply Devanagari+ProperNoun): {', '.join(proper_words)}\n"
    if devan_words:  hint_block += f"NON-ENGLISH sounds detected (apply D3-Devanagari): {', '.join(devan_words)}\n"
    if mb_words:     hint_block += f"POSSIBLY UNINTELLIGIBLE (apply MB tag): {', '.join(mb_words)}\n"

    user_msg = (
        f"File: {filename}\n"
        f"Reference text (what speaker was supposed to say): {ref or 'Not provided'}\n"
        f"Total words to annotate: {len(words)}\n\n"
        f"=== SILENCE GAPS >2s — each MUST become its own SIL annotation entry ===\n"
        f"{silence_notes}\n\n"
        f"{hint_block}"
        f"\n=== WORD LIST — apply decision tree to every single word ===\n"
        f"Format: \"word\" [start -> end] HINT:type\n"
        f"HINT guide: LIKELY_FILLER->FIL tag | LIKELY_PROPER_NOUN->Devanagari+ProperNoun | "
        f"LIKELY_DEVANAGARI->D3-Devanagari | LIKELY_MB->MB tag | NORMAL->steps 4-6\n\n"
        f"{words_fmt}\n\n"
        f"=== RAW WHISPER TRANSCRIPT (context only) ===\n"
        f"{transcript}\n\n"
        f"=== YOUR TASK ===\n"
        f"Follow the 6-step decision tree from the system prompt for EVERY word.\n"
        f"Requirements:\n"
        f"- Annotate all {len(words)} words, do not skip any.\n"
        f"- Every silence gap listed above must appear as a SIL entry in annotations.\n"
        f"- FIL tag for: uh, uhh, um, umm, hmm, hm, er, erm, ah, ahh and similar sounds.\n"
        f"- ProperNoun+Devanagari for all names of people, places, brands, animals.\n"
        f"- D3-Devanagari for non-English sounds or unrecognisable mispronunciations.\n"
        f"- D1-English for clear recognisable English words only.\n"
        f"Return ONLY valid JSON. No markdown. No code fences.\n"
        f"The JSON MUST follow this exact schema — no other field names allowed:\n"
        f"{{\n"
        f"  \"annotations\": [\n"
        f"    {{\"original\": \"<whisper word>\", \"annotated\": \"<annotated form>\", "
        f"\"start\": \"<copy start timestamp exactly>\", \"end\": \"<copy end timestamp exactly>\", "
        f"\"rule\": \"<D1-English|D2-SubstituteEnglish|D3-Devanagari|FIL|MB|SIL|NOISE|LN>\"}},\n"
        f"    ...\n"
        f"  ],\n"
        f"  \"transcript\": \"<full annotated text joined with spaces>\",\n"
        f"  \"explanation\": \"<brief summary>\"\n"
        f"}}\n"
        f"CRITICAL: Copy start/end timestamps EXACTLY as given in the word list. Do not round or reformat them."
    )

    # ── Gemini PRIMARY ────────────────────────────────────────────────────────
    if GEMINI_KEYS:
        print(f"[*] Annotating {len(words)} words via Gemini (primary)...")
        result = call_gemini_annotate(user_msg)
        if result.get("status") == "ok":
            return result
        print(f"[!] Gemini failed: {result.get('error')} — falling back to Groq")
    else:
        print("[!] No Gemini keys — trying Groq for annotation")

    # ── Groq FALLBACK ─────────────────────────────────────────────────────────
    if not GROQ_KEYS:
        return {"error": (
            "Annotation failed: No Gemini keys available and no Groq fallback keys. "
            "Set GEMINI_KEY in your Leapcell environment variables."
        )}

    print(f"[*] Annotating {len(words)} words via Groq (fallback)...")
    attempted = set()
    while True:
        key = _get_next_groq_key()
        if key is None or key in attempted:
            return {"error": "All annotation services failed. Check your API keys."}
        attempted.add(key)
        try:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                   {"role": "user",   "content": user_msg}],
                      "max_tokens": 8000, "temperature": 0.1},
                timeout=60
            )
            if resp.status_code == 429:
                print(f"[!] Groq key rate-limited — rotating to next key")
                _mark_key_exhausted(key); continue
            if resp.status_code != 200:
                return {"error": f"Groq Error {resp.status_code}: {resp.text[:300]}"}
            raw = resp.json()["choices"][0]["message"]["content"]
            return parse_ai_response(raw)
        except requests.exceptions.Timeout:
            print(f"[!] Groq request timed out — rotating key and retrying")
            _mark_key_exhausted(key); continue
        except Exception as e:
            return {"error": str(e)}


def call_gemini_annotate(user_msg):
    """Try each Gemini key in rotation until one succeeds."""
    if not GEMINI_KEYS:
        return {"error": "No Gemini keys configured"}
    for attempt in range(len(GEMINI_KEYS)):
        key = _get_next_gemini_key()
        try:
            resp = requests.post(
                f"{GEMINI_URL}?key={key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_msg}]}],
                      "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8000}},
                timeout=180
            )
            if resp.status_code == 429:
                print(f"[!] Gemini key rate-limited — rotating to next key")
                continue
            if resp.status_code != 200:
                print(f"[!] Gemini key error {resp.status_code} — rotating")
                continue
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return parse_ai_response(raw)
        except Exception as e:
            print(f"[!] Gemini attempt {attempt+1} error: {str(e)} — rotating")
            continue
    return {"error": "All Gemini keys failed or rate-limited"}


def _normalize_annotation(a):
    original  = (a.get('original')   or a.get('word')        or
                 a.get('original_word') or a.get('whisper_word') or '')
    annotated = (a.get('annotated')  or a.get('annotation')  or
                 a.get('transcription') or a.get('text')      or original)
    start     = (a.get('start')      or a.get('start_time')  or
                 a.get('startTime')  or a.get('time_start')   or '')
    end       = (a.get('end')        or a.get('end_time')    or
                 a.get('endTime')    or a.get('time_end')     or '')
    rule      = (a.get('rule')       or a.get('decision')    or
                 a.get('rule_applied') or a.get('type')       or
                 a.get('label')      or '')
    result = dict(a)
    result.update({'original': original, 'annotated': annotated,
                   'start': start, 'end': end, 'rule': rule})
    return result


def _build_result_from_anns(anns, filename="audio.wav"):
    import random
    normalized = [_normalize_annotation(a) for a in anns]
    transcript = " ".join(a.get("annotated", "") for a in normalized)
    return {
        "transcript": transcript,
        "annotations": normalized,
        "explanation": "Parsed successfully.",
        "annotic_json": {
            "file_name": filename,
            "id": random.randint(10000, 99999),
            "annotations": [
                {"start": a.get("start", ""), "end": a.get("end", ""),
                 "original": a.get("original", ""),
                 "annotated": a.get("annotated", ""),
                 "rule": a.get("rule", ""),
                 "Transcription": [a.get("annotated", "")]}
                for a in normalized
            ]
        }
    }


def parse_ai_response(raw):
    import re, random

    cleaned = raw.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    def try1(): return json.loads(cleaned)
    def try2(): return json.loads(re.search(r'\{[\s\S]*\}', cleaned).group())
    def try3(): return json.loads(re.sub(r',\s*([}\]])', r'\1', cleaned))
    def try4(): return json.loads(re.sub(r',\s*([}\]])', r'\1', re.search(r'\{[\s\S]*\}', cleaned).group()))
    def try5(): return json.loads(cleaned.encode('utf-8').decode('utf-8-sig'))

    for i, attempt in enumerate([try1, try2, try3, try4, try5], 1):
        try:
            parsed = attempt()
            if isinstance(parsed, list):
                print(f"[*] AI returned bare array with {len(parsed)} items — wrapping")
                result = _build_result_from_anns(parsed)
                return {"status": "ok", "result": result}
            if "annotic_json" in parsed:
                parsed["annotic_json"]["id"] = random.randint(10000, 99999)
            if "annotations" in parsed and isinstance(parsed["annotations"], list):
                parsed["annotations"] = [_normalize_annotation(a) for a in parsed["annotations"]]
                parsed["transcript"] = " ".join(a.get("annotated","") for a in parsed["annotations"])
            print(f"[*] Done! {len(parsed.get('annotations', []))} annotations")
            return {"status": "ok", "result": parsed}
        except Exception as e:
            print(f"[!] Parse attempt {i} failed: {e}")

    try:
        ann_match = re.search(r'"annotations"\s*:\s*(\[[\s\S]*?\])\s*[,}]', cleaned)
        if ann_match:
            anns = json.loads(ann_match.group(1))
            result = _build_result_from_anns(anns)
            result["explanation"] = "Parsed via annotations-key fallback."
            print(f"[*] Done via fallback A! {len(anns)} annotations")
            return {"status": "ok", "result": result}
    except Exception as e:
        print(f"[!] Fallback A failed: {e}")

    try:
        obj_matches = re.findall(r'\{[^{}]*"annotated"[^{}]*\}', cleaned)
        if obj_matches:
            anns = [json.loads(o) for o in obj_matches]
            result = _build_result_from_anns(anns)
            result["explanation"] = f"Parsed via object-salvage fallback ({len(anns)} recovered)."
            print(f"[*] Done via fallback B! Salvaged {len(anns)} annotation objects")
            return {"status": "ok", "result": result}
    except Exception as e:
        print(f"[!] Fallback B failed: {e}")

    print(f"[!] Could not parse response. Raw (first 500 chars): {raw[:500]}")
    return {"error": "Could not parse AI response. Please try again.", "raw": raw[:500]}


if __name__ == '__main__':
    import threading, webbrowser, time

    print("=" * 55)
    print("  AnnotoAI — Full Pipeline")
    print("=" * 55)
    print(f"  URL          : http://localhost:{PORT}")
    print(f"  Transcription: {'AssemblyAI x' + str(len(ASSEMBLYAI_KEYS)) + ' (primary)' if ASSEMBLYAI_KEYS else 'Groq Whisper only (fallback)' if GROQ_KEYS else '❌ NO KEYS SET'}")
    print(f"  Annotation   : {'Gemini x' + str(len(GEMINI_KEYS)) + ' (primary)' if GEMINI_KEYS else 'Groq LLM only (fallback)' if GROQ_KEYS else '❌ NO KEYS SET'}")
    print(f"  Groq keys    : {len(GROQ_KEYS)} (fallback only)")
    print(f"  Auth         : {'Enabled' if AUTH_ENABLED else 'Disabled'}")
    print()
    print("  DO NOT CLOSE THIS WINDOW!")
    print("=" * 55)

    _is_cloud = os.environ.get('LEAPCELL') or os.environ.get('LEAPCELL_APP_NAME')
    if not _is_cloud:
        def open_browser():
            time.sleep(2)
            webbrowser.open(f'http://localhost:{PORT}')
        threading.Thread(target=open_browser, daemon=True).start()
    server = http.server.HTTPServer(('0.0.0.0', PORT), AnnotoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
