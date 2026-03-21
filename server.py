import http.server
import json
import os
import cgi
import tempfile
import webbrowser
import threading
import time
import subprocess
import sys

PORT = 7842
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# ══════════════════════════════════════════════════════
# LOAD API KEYS FROM config.py (keeps keys out of GitHub)
# ══════════════════════════════════════════════════════
try:
    from config import GROQ_KEYS, GEMINI_KEY
    print(f"[*] Loaded {len(GROQ_KEYS)} Groq key(s) from config.py")
except ImportError:
    print("[!] config.py not found — using empty keys. Create config.py!")
    GROQ_KEYS  = []
    GEMINI_KEY = ""

# ── Key rotation state (persists while server is running) ──
_groq_key_index   = 0        # which Groq key to try next
_groq_exhausted   = set()    # keys that hit rate limit today
_last_reset_day   = None     # track daily reset

try:
    import requests
except ImportError:
    print("[*] Installing requests...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--quiet"])
    import requests


# ══════════════════════════════════════════════════════════════════════════════
# COMPLETE SYSTEM PROMPT — ALL RULES FROM ANNOTATION GUIDELINES (Jan 2026)
# ══════════════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """Speech annotation AI — DesicrewAI Spoken English Assessment (Jan 2026).

YOU ARE AN ANNOTATOR, NOT A TRANSLATOR. NEVER CONVERT ENGLISH TO HINDI.

══ GOLDEN RULE ══
Whisper gives you English words. If it's a real English word pronounced recognisably → KEEP IN ENGLISH.
Only use Devanagari in the 4 cases listed below.

ALWAYS KEEP IN ENGLISH (never convert):
a, an, the, I, you, he, she, it, we, they, me, him, her, us, them, my, his, its, our, their,
is, are, was, were, be, been, have, has, had, do, does, did, will, would, shall, should,
may, might, can, could, must, and, or, but, so, if, as, at, by, for, from, in, into, of,
on, out, to, up, with, about, after, before, through, this, that, these, those, here, there,
what, which, who, when, where, why, how, today, we, will, take, about, safety, piston, use,
post, allow, keep, your, hands, go, get, give, come, make, know, think, see, look, want,
find, tell, ask, say, said, went, came, told, work, help, good, great, new, old, long, time,
day, year, people, way, man, woman, child, world, life, hand, place, home, water, name, word

══ CORE PRINCIPLES (Page 2) ══
1. Transcribe the WHOLE audio as heard — including words not in reference text.
2. Accent variations tolerated if word is still recognisable as English.
   OK: "de-VEL-op-ment" / "DE-vel-op-ment" → development
   OK: "E-du-kay-shon" / "E-joo-kay-shun" → education
   NOT OK: "E-zu-ka-shon" (implausible) → Devanagari
3. UK, US, Indian English all valid. Use as tie-breakers.
4. Correct pronunciation → keep reference word. Incorrect → transcribe as heard.

══ 3 DECISIONS ══
D1 KEEP ENGLISH (90%+ of words): Real English word + recognisable pronunciation → keep as-is.
D2 SUBSTITUTE ENGLISH (rare): Mispronunciation sounds like a DIFFERENT English word → write that word.
   colon heard as "kuh-lr" → colour | man heard as "main" → main | house heard as "horse" → horse
D3 DEVANAGARI (only 4 cases):
   a) Proper noun (person/place/animal) — always Devanagari even if pronounced correctly
   b) Mispronunciation sounds like NO English word
   c) Non-English / gibberish sound
   d) Special: filler, mumble, letter-spelling, stretched word (see tags)

══ RULES FROM GUIDELINES ══
g) PROPER NOUNS → always Devanagari: Karthik→कार्तिक, England→इंग्लेंड, Mumbai→मुंबई
   "king" as generic word → English. "King" as title/name → Devanagari.

e) SUB-LEXICAL PAUSES: Word spoken with intra-word breaks → evaluate each part independently.
   "prolong" as "pro"+"long" → pro long (both valid English)
   "compute" as "com"+"pute" → कं पूट (parts not valid English alone)
   "vineyard" as "vin"+"yard" → विन yard ("vin" not valid English)

f) SUB-LEXICAL STRETCH: Word spoken with elongated syllables → full word in Devanagari + ONE extra vowel.
   "coming" as "co..ming.." → कअमिंगअ

h) FALSE STARTS / REPETITIONS → transcribe verbatim as heard.
   "c-c-clown" → क क clown | "f-i-r-e fire" → एफ आई आर ई fire

i) PUNCTUATION WITHIN WORDS → include as heard.
   "you're" → you're | "dog's" → dog's | "catch-up" → catch-up

c) INSERTED WORDS (not in reference) → English if valid word, else Devanagari.

d) LETTER NAMES → <LN> tag per letter, content in Devanagari.
   A→ए B→बी C→सी D→डी E→ई F→एफ G→जी H→एच I→आई J→जे K→के L→एल M→एम
   N→एन O→ओ P→पी Q→क्यू R→आर S→एस T→टी U→यू V→वी W→डब्लू X→एक्स Y→वाय Z→ज़ेड
   balloon → <LN>बी</LN><LN>ए</LN><LN>एल</LN><LN>एल</LN><LN>ओ</LN><LN>ओ</LN><LN>एन</LN>

══ 5 TAGS ══
All tags need open+close. Tags not mutually exclusive. Tag EACH word/part separately.

<MB></MB> — completely unintelligible, cannot write in English or Devanagari. Use empty: <MB></MB>

<NOISE></NOISE> — background noise.
  Only noise → <NOISE></NOISE> | Speech with noise → <NOISE>word</NOISE>

<LN></LN> — letter-by-letter spelling. One tag per letter. Content in Devanagari.

<FIL></FIL> — ONLY genuine thinking/hesitation sounds. NOT the English article "a" or pronoun "I".
  ✅ FILLER: "uhhh" "ummmm" "aaah" "hmm" (drawn-out hesitation sounds)
  ❌ NOT FILLER: "a" (article) | "I" (pronoun) | "oh" (genuine reaction)
  uh/uhh→<FIL>अ</FIL> | um/umm→<FIL>अम</FIL> | aah/aaah→<FIL>आ</FIL>
  hmm→<FIL>हम</FIL> | eh→<FIL>ए</FIL> | er/erm→<FIL>अर</FIL>
  haan→<FIL>हाँ</FIL> | ohh→<FIL>ओ</FIL> | mm/mmm→<FIL>म</FIL>
  Filler + noise → <NOISE><FIL>आ</FIL></NOISE>

<SIL></SIL> — silence > 2 seconds. MUST include exact timestamps from silence_gaps list.
  Each SIL = its own annotation entry: original:"<SIL>", annotated:"<SIL></SIL>",
  start: sil_start timestamp, end: sil_end timestamp, rule:"SIL"
  Covers ALL silences: before first word, between words, after last word.

══ DEVANAGARI CHART ══
Vowels: a→अ aa→आ i→इ ee→ई u→उ oo→ऊ e→ए ai→ऐ o→ओ au→औ
Consonants: k→क kh→ख g→ग ch→च j→ज t→त th→थ d→द n→न
T(hard)→ट D(hard)→ड p→प ph/f→फ b→ब m→म r→र l→ल v/w→व sh→श s→स h→ह y→य
Halant(abrupt end)→् Anusvara(nasal)→ं
Matras: का ki कि kee की ku कु koo कू ke के ko को

══ OUTPUT FORMAT — ONLY valid JSON, no markdown ══
{
  "transcript": "full annotated transcript string",
  "annotations": [
    {"original":"whisper word","annotated":"English OR देवनागरी OR <TAG>x</TAG>",
     "start":"0:00:00.000000","end":"0:00:00.000000",
     "rule":"D1-English/D2-SubstituteEnglish/D3-Devanagari/ProperNoun/SubLexPause/SubLexStretch/FalseStart/LN/FIL/MB/NOISE/SIL"}
  ],
  "explanation": "2-3 sentences on key decisions",
  "annotic_json": {
    "file_name": "filename.wav",
    "annotations": [
      {"start":"0:00:00.000000","end":"0:00:00.000000","Transcription":["annotated word"]}
    ]
  }
}

══ 12-STEP SELF-CHECK (every word) ══
1. Genuine hesitation sound (uhhh/umm/aaah/hmm) — NOT article "a" or pronoun "I"? → <FIL>
2. Completely unintelligible? → <MB></MB>
3. Background noise? → <NOISE>word</NOISE>
4. Silence > 2s? → <SIL></SIL> with exact sil_start/sil_end timestamps
5. Letters being spelled out? → <LN>देवनागरी</LN> per letter
6. Proper noun (person/place/animal)? → Devanagari
7. Stretched/elongated syllables? → full word Devanagari + extra vowel
8. False start or stutter? → verbatim
9. Intra-word pause? → evaluate each part independently
10. *** REAL ENGLISH WORD? → KEEP IN ENGLISH. DO NOT CONVERT. ***
11. Mispronunciation = different English word? → that English word
12. Nothing matched → Devanagari phonetically

Step 10 covers 90%+ of words. YOU ARE AN ANNOTATOR. NOT A TRANSLATOR."""


class AnnotoHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path in ['/', '/index.html']:
            self.serve_html()
        elif self.path == '/check':
            self.send_json({"status": "ok"})
        elif self.path == '/test-keys':
            self.test_all_keys()
        else:
            self.send_response(404)
            self.end_headers()

    def test_all_keys(self):
        """Test every Groq key and return status of each."""
        print("[*] Testing all Groq keys...")
        results = []
        for i, key in enumerate(GROQ_KEYS):
            masked = key[:8] + "..." + key[-4:]
            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "user", "content": "Say OK"}],
                        "max_tokens": 5,
                        "temperature": 0.0
                    },
                    timeout=15
                )
                if resp.status_code == 200:
                    status = "✅ WORKING"
                    print(f"[*] Key {i+1} ({masked}): WORKING")
                elif resp.status_code == 429:
                    status = "⚠️ RATE LIMITED (valid key, limit hit)"
                    print(f"[*] Key {i+1} ({masked}): RATE LIMITED")
                elif resp.status_code == 401:
                    status = "❌ INVALID KEY"
                    print(f"[!] Key {i+1} ({masked}): INVALID")
                else:
                    status = f"❌ ERROR {resp.status_code}"
                    print(f"[!] Key {i+1} ({masked}): ERROR {resp.status_code}")
            except Exception as e:
                status = f"❌ FAILED: {str(e)[:50]}"
                print(f"[!] Key {i+1} ({masked}): FAILED - {e}")

            results.append({
                "key_number": i + 1,
                "key_masked": masked,
                "status": status
            })

        # Test Gemini too
        gemini_status = "⚠️ Not configured"
        if GEMINI_KEY:
            try:
                resp = requests.post(
                    f"{GEMINI_URL}?key={GEMINI_KEY}",
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": "Say OK"}]}],
                          "generationConfig": {"maxOutputTokens": 5}},
                    timeout=15
                )
                gemini_status = "✅ WORKING" if resp.status_code == 200 else f"❌ ERROR {resp.status_code}"
            except Exception as e:
                gemini_status = f"❌ FAILED: {str(e)[:50]}"

        working   = sum(1 for r in results if "WORKING" in r["status"])
        limited   = sum(1 for r in results if "RATE LIMITED" in r["status"])
        invalid   = sum(1 for r in results if "INVALID" in r["status"])

        self.send_json({
            "summary": {
                "total_keys":    len(GROQ_KEYS),
                "working":       working,
                "rate_limited":  limited,
                "invalid":       invalid,
                "gemini_backup": gemini_status,
                "daily_capacity": f"{working * 100000:,} tokens/day from working keys"
            },
            "keys": results
        })

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        content_type = self.headers.get('Content-Type', '')
        if self.path == '/transcribe' and 'multipart' in content_type:
            self.handle_audio_upload()
        elif self.path == '/transcribe-url':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            self.handle_audio_url(body.get('url', ''))
        elif self.path == '/set-key':
            length = int(self.headers.get('Content-Length', 0))
            self.rfile.read(length)
            self.send_json({"status": "ok"})
        elif self.path == '/annotate':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            result = self.call_groq(body)
            self.send_json(result)
        else:
            self.send_response(404)
            self.end_headers()

    def handle_audio_upload(self):
        print("[*] Receiving audio file...")
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST',
                         'CONTENT_TYPE': self.headers['Content-Type']}
            )
            file_item = form['audio']
            filename  = file_item.filename or 'audio.wav'
            ext       = os.path.splitext(filename)[1] or '.wav'
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=BASE_DIR)
            tmp.write(file_item.file.read())
            tmp.close()
            print("[*] Saved:", tmp.name)
            result = self.run_whisper(tmp.name, filename)
            os.unlink(tmp.name)
            self.send_json(result)
        except Exception as e:
            print("[!] Upload error:", e)
            self.send_json({"error": str(e)})

    def handle_audio_url(self, url):
        print("[*] Downloading audio from URL...")
        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                self.send_json({"error": "Could not download: " + str(resp.status_code)})
                return
            ext = '.wav'
            if 'mp3' in url:
                ext = '.mp3'
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=BASE_DIR)
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp.close()
            filename = url.split('/')[-1].split('?')[0] or 'audio.wav'
            result   = self.run_whisper(tmp.name, filename)
            os.unlink(tmp.name)
            self.send_json(result)
        except Exception as e:
            print("[!] URL error:", e)
            self.send_json({"error": str(e)})

    def run_whisper(self, audio_path, original_filename):
        print("[*] Running Whisper on:", audio_path)
        transcribe_script = os.path.join(BASE_DIR, 'transcribe.py')
        result = subprocess.run(
            [sys.executable, transcribe_script, audio_path],
            capture_output=True, text=True, timeout=600, cwd=BASE_DIR
        )
        if result.returncode != 0:
            print("[!] Whisper error:", result.stderr)
            return {"error": "Whisper failed: " + result.stderr}
        json_path = os.path.join(BASE_DIR, 'transcript_output.json')
        if not os.path.exists(json_path):
            return {"error": "transcript_output.json not found"}
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['audio_file'] = original_filename
        print("[*] Transcribed:", len(data.get('words', [])), "words")
        return {"status": "ok", "result": data}

    # ─────────────────────────────────────────────────────
    # KEY ROTATION HELPERS
    # ─────────────────────────────────────────────────────
    def _get_next_groq_key(self):
        """Return the next available Groq key, cycling through all keys."""
        global _groq_key_index, _groq_exhausted, _last_reset_day
        import datetime
        today = datetime.date.today().isoformat()
        # Reset exhausted keys at start of new day
        if _last_reset_day != today:
            _groq_exhausted = set()
            _groq_key_index = 0
            _last_reset_day = today
            print("[*] New day — all Groq keys reset!")
        available = [k for i, k in enumerate(GROQ_KEYS) if i not in _groq_exhausted]
        if not available:
            return None
        key = available[_groq_key_index % len(available)]
        _groq_key_index = (_groq_key_index + 1) % len(available)
        return key

    def _mark_key_exhausted(self, key):
        """Mark a key as rate-limited for today."""
        global _groq_exhausted
        try:
            idx = GROQ_KEYS.index(key)
            _groq_exhausted.add(idx)
            remaining = len(GROQ_KEYS) - len(_groq_exhausted)
            print(f"[!] Groq key #{idx+1} rate-limited. {remaining} key(s) remaining today.")
        except ValueError:
            pass

    def _call_gemini(self, system_prompt, user_msg):
        """Fallback to Gemini API when all Groq keys are exhausted."""
        if not GEMINI_KEY:
            return {"error": "All Groq keys exhausted and no Gemini key configured. Add GEMINI_KEY in server.py or add more Groq keys."}
        print("[*] Falling back to Gemini API...")
        try:
            combined = system_prompt + "\n\n" + user_msg
            resp = requests.post(
                f"{GEMINI_URL}?key={GEMINI_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": combined}]}],
                    "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8000}
                },
                timeout=180
            )
            if resp.status_code != 200:
                return {"error": f"Gemini Error {resp.status_code}: {resp.text[:300]}"}
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return {"status": "ok", "raw": raw, "provider": "gemini"}
        except Exception as e:
            return {"error": f"Gemini error: {str(e)}"}

    def _parse_ai_response(self, raw, filename):
        """Parse JSON from AI response — multiple fallback strategies."""
        import re, random

        # ── Clean common AI response wrapping ────────────────
        cleaned = raw.strip()
        # Remove markdown code blocks
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*", "", cleaned)
        cleaned = cleaned.strip()

        # ── Strategy 1: direct parse ──────────────────────────
        try:
            parsed = json.loads(cleaned)
            if "annotic_json" in parsed:
                parsed["annotic_json"]["id"] = random.randint(10000, 99999)
            return {"status": "ok", "result": parsed}
        except Exception:
            pass

        # ── Strategy 2: find outermost { } ───────────────────
        try:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                parsed = json.loads(match.group())
                if "annotic_json" in parsed:
                    parsed["annotic_json"]["id"] = random.randint(10000, 99999)
                return {"status": "ok", "result": parsed}
        except Exception:
            pass

        # ── Strategy 3: fix trailing commas & retry ───────────
        try:
            fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
            parsed = json.loads(fixed)
            if "annotic_json" in parsed:
                parsed["annotic_json"]["id"] = random.randint(10000, 99999)
            return {"status": "ok", "result": parsed}
        except Exception:
            pass

        # ── Strategy 4: fix trailing commas on extracted JSON ─
        try:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                fixed = re.sub(r",\s*([}\]])", r"\1", match.group())
                parsed = json.loads(fixed)
                if "annotic_json" in parsed:
                    parsed["annotic_json"]["id"] = random.randint(10000, 99999)
                return {"status": "ok", "result": parsed}
        except Exception:
            pass

        # ── Strategy 5: truncated response — build minimal result
        # AI may have hit token limit mid-response
        print(f"[!] JSON parse failed — raw response starts with: {raw[:200]}")
        print(f"[!] Raw response ends with: {raw[-200:]}")

        # Try to salvage partial annotations if possible
        try:
            # Find annotations array even if JSON is incomplete
            ann_match = re.search(r'"annotations"\s*:\s*(\[[\s\S]*)', cleaned)
            if ann_match:
                # Try to close the truncated array
                partial = ann_match.group(1)
                # Find last complete annotation object
                last_obj = partial.rfind("},")
                if last_obj > 0:
                    partial_fixed = partial[:last_obj+1] + "]"
                    annotations = json.loads(partial_fixed)
                    print(f"[*] Salvaged {len(annotations)} annotations from truncated response")
                    result = {
                        "transcript": "",
                        "annotations": annotations,
                        "explanation": "Partial result — response was truncated",
                        "annotic_json": {
                            "file_name": filename,
                            "id": random.randint(10000, 99999),
                            "annotations": [
                                {"start": a.get("start",""), "end": a.get("end",""),
                                 "Transcription": [a.get("annotated","")]}
                                for a in annotations
                            ]
                        }
                    }
                    return {"status": "ok", "result": result}
        except Exception:
            pass

        # ── All strategies failed ─────────────────────────────
        return {
            "error": "Could not parse AI response. The response may have been cut off. Try with a shorter audio clip.",
            "raw": raw[:300]
        }

    def _chunk_words(self, words, chunk_size=60):
        """Split words into chunks to avoid token limit issues."""
        return [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]

    def _merge_results(self, results, filename):
        """Merge multiple chunk results into one final result."""
        import random
        all_annotations = []
        all_annotic    = []
        transcript_parts = []

        for r in results:
            if "result" in r:
                res = r["result"]
                all_annotations.extend(res.get("annotations", []))
                all_annotic.extend(res.get("annotic_json", {}).get("annotations", []))
                t = res.get("transcript", "")
                if t:
                    transcript_parts.append(t)

        return {
            "status": "ok",
            "result": {
                "transcript":  " ".join(transcript_parts),
                "annotations": all_annotations,
                "explanation": f"Processed in {len(results)} chunk(s). Total: {len(all_annotations)} annotations.",
                "annotic_json": {
                    "file_name":   filename,
                    "id":          random.randint(10000, 99999),
                    "annotations": all_annotic
                }
            }
        }

    # ─────────────────────────────────────────────────────
    # MAIN ANNOTATION FUNCTION
    # ─────────────────────────────────────────────────────
    def call_groq(self, payload):
        ref        = payload.get("reference", "")
        words      = payload.get("words", [])
        transcript = payload.get("transcript", "")
        filename   = payload.get("filename", "audio.wav")
        silence_gaps  = payload.get("silence_gaps", [])
        sublex_pauses = payload.get("sublex_pauses", [])

        # ── Chunk if too many words (avoid token limit) ─────
        CHUNK_SIZE = 80  # words per API call — safe limit
        if len(words) > CHUNK_SIZE:
            print(f"[*] {len(words)} words — splitting into chunks of {CHUNK_SIZE}...")
            chunks  = self._chunk_words(words, CHUNK_SIZE)
            results = []
            for i, chunk in enumerate(chunks):
                print(f"[*] Processing chunk {i+1}/{len(chunks)} ({len(chunk)} words)...")
                chunk_payload = dict(payload)
                chunk_payload["words"] = chunk
                chunk_payload["transcript"] = " ".join(w["word"] for w in chunk)
                # Pass silence gaps only relevant to this chunk
                chunk_start = chunk[0]["start_seconds"] if chunk else 0
                chunk_end   = chunk[-1]["end_seconds"]   if chunk else 0
                chunk_payload["silence_gaps"] = [
                    s for s in silence_gaps
                    if chunk_start <= float(s.get("gap_seconds", 0)) <= chunk_end
                ]
                result = self._annotate_chunk(chunk_payload)
                results.append(result)
                if "error" in result:
                    print(f"[!] Chunk {i+1} failed: {result['error']}")
            return self._merge_results(results, filename)

        # ── Format word list ──────────────────────────────
        words_fmt = "\n".join([
            f'"{w["word"]}" [{w["start"]} -> {w["end"]}] HINT:{w.get("hint","NORMAL")}'
            for w in words
        ])

        # ── Detect silence gaps if not passed ─────────────
        def to_secs(t):
            try:
                p = t.split(":")
                return int(p[0])*3600 + int(p[1])*60 + float(p[2])
            except Exception:
                return 0

        if not silence_gaps:
            for i in range(len(words) - 1):
                gap = to_secs(words[i+1]["start"]) - to_secs(words[i]["end"])
                if gap > 2.0:
                    silence_gaps.append({
                        "after_word":  words[i]["word"],
                        "before_word": words[i+1]["word"],
                        "gap_seconds": round(gap, 2),
                        "sil_start":   words[i]["end"],
                        "sil_end":     words[i+1]["start"],
                    })

        # ── Format silence notes ───────────────────────────
        silence_lines = []
        for idx, s in enumerate(silence_gaps):
            sil_start = s.get("sil_start", "0:00:00.000000")
            sil_end   = s.get("sil_end",   "0:00:00.000000")
            gap       = s.get("gap_seconds", 0)
            if s.get("type") == "leading":
                silence_lines.append(
                    f"[SIL #{idx+1}] LEADING {gap}s | SIL_START:{sil_start} SIL_END:{sil_end}"
                )
            else:
                silence_lines.append(
                    f"[SIL #{idx+1}] {gap}s between \'{s.get('after_word','')}\' and \'{s.get('before_word','')}\'"
                    f" | SIL_START:{sil_start} SIL_END:{sil_end}"
                )
        silence_notes = "\n".join(silence_lines) if silence_lines else "None"

        # ── Format sub-lexical hints ───────────────────────
        sublex_lines = [
            f"INTRA-PAUSE {sp['gap_seconds']}s between \'{sp['between'][0]}\' and \'{sp['between'][1]}\'"
            for sp in (sublex_pauses or []) if sp.get("gap_seconds", 0) > 0.05
        ]
        sublex_notes = "\n".join(sublex_lines[:15]) if sublex_lines else "None"

        # ── Optional hint sections ─────────────────────────
        optional = ""
        fw = [w["word"] for w in words if w.get("hint") == "LIKELY_FILLER"]
        mw = [w["word"] for w in words if "MB" in w.get("hint","")]
        pw = [w["word"] for w in words if w.get("hint") == "LIKELY_PROPER_NOUN"]
        lw = [w["word"] for w in words if w.get("hint") == "LIKELY_LETTER_SPELLING"]
        if fw: optional += f"FILLERS: {', '.join(fw)}\n"
        if mw: optional += f"MUMBLING: {', '.join(mw)}\n"
        if pw: optional += f"PROPER NOUNS: {', '.join(pw)}\n"
        if lw: optional += f"LETTER SPELLING: {', '.join(lw)}\n"

        # ── Build user message ─────────────────────────────
        user_msg = (
            f"File: {filename}\n"
            f"Reference: {ref or 'Not provided'}\n"
            f"Words: {len(words)}\n\n"
            f"SILENCES > 2s:\n{silence_notes}\n\n"
            f"INTRA-WORD PAUSES:\n{sublex_notes}\n\n"
            f"{optional}"
            f"WORDS:\n{words_fmt}\n\n"
            f"Transcript: {transcript}\n\n"
            f"RULES: Keep ALL real English words in English. "
            f"Devanagari ONLY for proper nouns, bad mispronunciation, fillers, mumble, letter-spelling, stretches. "
            f"SIL tags must use exact timestamps above. "
            f"Annotate ALL {len(words)} words.\n\n"
            f"IMPORTANT: Your response must be ONLY a valid JSON object. "
            f"Start your response with {{ and end with }}. "
            f"No text before or after the JSON. No markdown. No explanation outside JSON."
        )

        # ── Try Groq keys in rotation ──────────────────────
        return self._annotate_chunk(payload)

    def _annotate_chunk(self, payload):
        """Annotate a single chunk of words — builds full user message and calls API."""
        ref           = payload.get("reference", "")
        words         = payload.get("words", [])
        transcript    = payload.get("transcript", "")
        filename      = payload.get("filename", "audio.wav")
        silence_gaps  = payload.get("silence_gaps", [])
        sublex_pauses = payload.get("sublex_pauses", [])

        # ── Format word list ──────────────────────────────────
        words_fmt = "\n".join([
            f'"{w["word"]}" [{w["start"]} -> {w["end"]}] HINT:{w.get("hint","NORMAL")}'
            for w in words
        ])

        # ── Silence gaps ──────────────────────────────────────
        def to_secs(t):
            try:
                p = t.split(":")
                return int(p[0])*3600 + int(p[1])*60 + float(p[2])
            except Exception:
                return 0

        if not silence_gaps:
            for i in range(len(words) - 1):
                gap = to_secs(words[i+1]["start"]) - to_secs(words[i]["end"])
                if gap > 2.0:
                    silence_gaps.append({
                        "after_word":  words[i]["word"],
                        "before_word": words[i+1]["word"],
                        "gap_seconds": round(gap, 2),
                        "sil_start":   words[i]["end"],
                        "sil_end":     words[i+1]["start"],
                    })

        silence_lines = []
        for idx, s in enumerate(silence_gaps):
            sil_start = s.get("sil_start", "0:00:00.000000")
            sil_end   = s.get("sil_end",   "0:00:00.000000")
            gap       = s.get("gap_seconds", 0)
            if s.get("type") == "leading":
                silence_lines.append(f"[SIL #{idx+1}] LEADING {gap}s | START:{sil_start} END:{sil_end}")
            else:
                silence_lines.append(f"[SIL #{idx+1}] {gap}s between \'{s.get('after_word','')}\' and \'{s.get('before_word','')}\' | START:{sil_start} END:{sil_end}")
        silence_notes = "\n".join(silence_lines) if silence_lines else "None"

        # ── Sub-lexical pauses ────────────────────────────────
        sublex_lines = [
            f"INTRA-PAUSE {sp['gap_seconds']}s between \'{sp['between'][0]}\' and \'{sp['between'][1]}\'"
            for sp in (sublex_pauses or []) if sp.get("gap_seconds", 0) > 0.05
        ]
        sublex_notes = "\n".join(sublex_lines[:15]) if sublex_lines else "None"

        # ── Hint sections ─────────────────────────────────────
        optional = ""
        fw = [w["word"] for w in words if w.get("hint") == "LIKELY_FILLER"]
        mw = [w["word"] for w in words if "MB" in w.get("hint","")]
        pw = [w["word"] for w in words if w.get("hint") == "LIKELY_PROPER_NOUN"]
        lw = [w["word"] for w in words if w.get("hint") == "LIKELY_LETTER_SPELLING"]
        if fw: optional += f"FILLERS: {', '.join(fw)}\n"
        if mw: optional += f"MUMBLING: {', '.join(mw)}\n"
        if pw: optional += f"PROPER NOUNS: {', '.join(pw)}\n"
        if lw: optional += f"LETTER SPELLING: {', '.join(lw)}\n"

        # ── Build complete user message ───────────────────────
        user_msg = (
            f"File: {filename}\n"
            f"Reference: {ref or 'Not provided'}\n"
            f"Total words: {len(words)}\n\n"
            f"SILENCES > 2s:\n{silence_notes}\n\n"
            f"INTRA-WORD PAUSES:\n{sublex_notes}\n\n"
            f"{optional}"
            f"WORDS WITH TIMESTAMPS:\n{words_fmt}\n\n"
            f"Full transcript: {transcript}\n\n"
            f"RULES: Keep ALL real English words in English. "
            f"Devanagari ONLY for proper nouns, bad mispronunciation, fillers, mumble, letter-spelling, stretches. "
            f"SIL tags must use exact timestamps from the silence list above. "
            f"Annotate ALL {len(words)} words.\n\n"
            f"IMPORTANT: Respond with ONLY a valid JSON object. "
            f"Start with {{ and end with }}. No text before or after. No markdown."
        )

        # ── Try Groq keys in rotation ─────────────────────────
        print(f"[*] Annotating {len(words)} words...")
        attempted_keys = set()

        while True:
            key = self._get_next_groq_key()

            if key is None:
                print("[!] All Groq keys exhausted — trying Gemini...")
                gem = self._call_gemini(SYSTEM_PROMPT, user_msg)
                if "error" in gem:
                    return gem
                return self._parse_ai_response(gem["raw"], filename)

            if key in attempted_keys:
                print("[!] All keys tried — trying Gemini...")
                gem = self._call_gemini(SYSTEM_PROMPT, user_msg)
                if "error" in gem:
                    return gem
                return self._parse_ai_response(gem["raw"], filename)

            attempted_keys.add(key)

            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type":  "application/json"
                    },
                    json={
                        "model":       "llama-3.3-70b-versatile",
                        "messages":    [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user",   "content": user_msg}
                        ],
                        "max_tokens":  32000,
                        "temperature": 0.0
                    },
                    timeout=180
                )

                if resp.status_code == 429:
                    self._mark_key_exhausted(key)
                    continue

                if resp.status_code != 200:
                    print(f"[!] Groq error {resp.status_code}: {resp.text[:200]}")
                    return {"error": f"Groq Error {resp.status_code}: {resp.text[:300]}"}

                raw = resp.json()["choices"][0]["message"]["content"]
                print(f"[*] Response: {len(raw)} chars | starts: {raw[:80]}")
                result = self._parse_ai_response(raw, filename)
                if "result" in result:
                    print(f"[*] Done! {len(result['result'].get('annotations',[]))} annotations")
                elif "error" in result:
                    print(f"[!] Parse failed. Raw:\n{raw[:500]}")
                return result

            except Exception as e:
                print(f"[!] Error: {e}")
                return {"error": str(e)}

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type',   'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def serve_html(self):
        html_path = os.path.join(BASE_DIR, 'annotation_tool.html')
        if os.path.exists(html_path):
            with open(html_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type',   'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'annotation_tool.html not found!')


def open_browser():
    time.sleep(2)
    webbrowser.open('http://localhost:' + str(PORT))


if __name__ == '__main__':
    print("=" * 60)
    print("  AnnotoAI — Full Rules Edition (Mar 2026)")
    print("=" * 60)
    print("  URL    : http://localhost:" + str(PORT))
    print("  Model  : llama-3.3-70b-versatile")
    print("  Whisper: small")
    print("  Tokens : 32000")
    print()
    print("  Rules implemented:")
    print("  ✓ Correct English pronunciation → keep English")
    print("  ✓ Incorrect → substituted English word")
    print("  ✓ Incorrect → Devanagari phonetic")
    print("  ✓ Proper nouns → Devanagari (g)")
    print("  ✓ Sub-lexical pauses (e)")
    print("  ✓ Sub-lexical stretches (f)")
    print("  ✓ False starts & repetitions (h)")
    print("  ✓ Punctuations within words (i)")
    print("  ✓ Inserted words (c)")
    print("  ✓ Letter names → <LN> tags (d)")
    print("  ✓ Fillers → <FIL> tags")
    print("  ✓ Mumbling → <MB> tags")
    print("  ✓ Noise → <NOISE> tags")
    print("  ✓ Silence > 2s → <SIL> tags")
    print()
    print("  DO NOT CLOSE THIS WINDOW!")
    print("=" * 60)
    threading.Thread(target=open_browser, daemon=True).start()
    server = http.server.HTTPServer(('localhost', PORT), AnnotoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped!")
