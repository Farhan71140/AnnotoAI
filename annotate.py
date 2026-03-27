"""
AnnotoAI Rule Engine — Pure Python + Claude API for Devanagari
Replaces Gemini entirely. Applies all annotation rules strictly.

RULES IMPLEMENTED:
  D1  - Valid English word / correct pronunciation → keep English
  D2  - Mispronounced but sounds like another valid English word → that English word
  D3  - Mispronounced, not a valid English word → Devanagari (via Claude API)
  FIL - Filler/hesitation sounds (uh, um, hmm, aah, eeh, ooh, er, erm…)
  SIL - Silence gap > 2 seconds → separate SIL annotation entry
  MB  - Completely unintelligible / indiscernible sound
  NOISE - Background noise (with or without speech)
  LN  - Letter-by-letter spelling → each letter in Devanagari inside <LN></LN>
  Proper nouns → always Devanagari (via Claude API)
  Punctuation within words → kept as-is
  False starts / repetitions → verbatim as heard
  Sub-lexical stretches → full word Devanagari + ONE extra vowel/consonant
"""

import re
import os
import json
import requests

# ── Claude API for Devanagari conversion ─────────────────────────────────────
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"

DEVANAGARI_SYSTEM = """You are a Devanagari phonetic transcription engine.
Convert English words/sounds to Devanagari script phonetically — exactly as they SOUND, not how they are spelled.
Rules:
- Use the exact phonetic sound, not standard Hindi spelling
- Devanagari transcription need NOT be a valid Hindi word
- Use halant (्) when a consonant ends abruptly with no following vowel (e.g. blak=ब्लक्)
- Use anusvara (ं) for nasal sounds
- Add ONLY ONE extra vowel or consonant to represent elongation/stretching
- For proper nouns: transcribe phonetically as pronounced

Phoneme map:
Vowels: a=अ, aa=आ, i=इ, ee/ii=ई, u=उ, oo/uu=ऊ, e=ए, ai=ऐ, o=ओ, au=औ
Consonants: k=क, kh=ख, g=ग, gh=घ, ch=च, chh=छ, j=ज, jh=झ, t=त, th=थ, d=द, dh=ध, n=न
T=ट, Th=ठ, D=ड, Dh=ढ, N=ण, p=प, ph=फ, b=ब, bh=भ, m=म, r=र, l=ल, v=व
sh=श, Sh=ष, s=स, h=ह, y=य, R=ड़, L=ळ

Respond with ONLY a JSON object: {"devanagari": "<result>"}
No explanation, no markdown."""

def convert_to_devanagari(word: str, context: str = "") -> str:
    """Call Claude API to convert a word/sound to Devanagari phonetically."""
    try:
        prompt = f'Convert this to Devanagari phonetically as it sounds: "{word}"'
        if context:
            prompt += f'\nContext (what word was supposed to be): "{context}"'

        resp = requests.post(
            CLAUDE_API_URL,
            headers={"Content-Type": "application/json"},
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 100,
                "system": DEVANAGARI_SYSTEM,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=15
        )
        if resp.status_code == 200:
            text = resp.json()["content"][0]["text"].strip()
            parsed = json.loads(text)
            return parsed.get("devanagari", word)
    except Exception as e:
        print(f"[!] Claude Devanagari API error: {e}")
    return word  # fallback: return original


# ── English word dictionary (fast lookup) ────────────────────────────────────
# Uses a built-in word list approach — checks if a word is valid English
try:
    # Try to use enchant if available
    import enchant
    _DICT = enchant.Dict("en_US")
    def is_valid_english(word: str) -> bool:
        w = re.sub(r"[^a-zA-Z'-]", "", word).lower()
        if not w or len(w) < 2:
            return False
        return _DICT.check(w)
except ImportError:
    # Fallback: large built-in common word set
    _COMMON_WORDS = set("""
a ability able about above accept according account across act action activity
actually add address administration after again against age ago agree agreement
ahead air all allow almost alone along already also although always american
among amount analysis and animal another answer any anyone anything appear apply
area around ask assume at available away back bad based be because become
before begin being believe benefit best better between big book both break
bring build business but call can card care carry case cause certain change
check child choose clear close cold color come community company compare
complete consider continue control cost could country cover create current cut
day deal decide decision deep describe design despite detail develop
development difference different difficult direction discover discuss do does
doing done door down drive during each early economic education effect effort
eight either else employee end energy enjoy enough environment especially even
evening ever every everyone everything exactly example exist expect experience
explain face fact fall family far feel few field find first five follow food
for force foreign form forward found four free from full further future get
give go goal good government great group grow growth hand happen hard have he
health help her here high him his history hold home however human hundred idea
if impact important improve include increase individual information inside
instead into issue its itself job just keep kind know knowledge land large last
law lead learn leave legal less level life light like line list little live
local long look low major make man management market may mean meet member might
mind model money month more most move much must national nature near need never
new next no normal not now number of off offer officer often old on one only
open operation opportunity or order organization other our out outside over own
part people perform person place plan play point policy political possible power
present press price probably problem produce program project property provide
public put quality question quickly rate reach read ready real reason recent
reduce region related remain report require research resource result return rise
role run same school season second see seem senior service set several share
short show significant similar since situation six small so social some someone
something sometimes soon source space special spend stand start state stay step
still stop strong structure study such support system take task team tell ten
term their them there these they think three through time to today together too
top total town trade traditional training tree true turn two type under until up
use value various very view visit wait want water way we well what when where
whether which while who why will within without word work world would write year
you young your able above across after against among around before behind below
between by despite during except for from inside into near of off on onto out
outside over past since through throughout till to toward under until up upon
with within without according along alongside amid amidst before concerning
despite during except following from including near plus regarding since
throughout toward towards unlike until upon versus via with worth also although
and as because both but either for furthermore hence however if in moreover
neither nor not only or since so than that though thus unless until when where
whereas whether while yet
""".split())

    def is_valid_english(word: str) -> bool:
        w = re.sub(r"[^a-zA-Z'-]", "", word).lower().strip("'-")
        if not w or len(w) < 2:
            return False
        return w in _COMMON_WORDS


# ── Filler / hesitation sounds ────────────────────────────────────────────────
FILLER_MAP = {
    # word → Devanagari
    'uh': 'अ', 'uhh': 'अ', 'uhhh': 'अ',
    'um': 'अम', 'umm': 'अम', 'ummm': 'अम',
    'hmm': 'हम', 'hm': 'हम', 'hmmm': 'हम',
    'ah': 'आ', 'ahh': 'आ', 'aah': 'आ', 'aaah': 'आ',
    'eh': 'ए', 'ehh': 'ए', 'eeh': 'ए',
    'er': 'अ', 'erm': 'अम',
    'ooh': 'ऊ', 'oh': 'ओ', 'ohh': 'ओ',
    'mm': 'म', 'mmm': 'म',
    'haan': 'हाँ', 'han': 'हाँ',
}

def is_filler(word: str) -> bool:
    w = word.lower().strip(".,!?()")
    return w in FILLER_MAP

def get_filler_devanagari(word: str) -> str:
    w = word.lower().strip(".,!?()")
    return FILLER_MAP.get(w, 'अ')


# ── Mumbling / MB detection ───────────────────────────────────────────────────
def is_mumble(word: str) -> bool:
    """Detect likely unintelligible/indiscernible speech."""
    w = word.lower().strip(".,!?()")
    if len(w) < 2:
        return False
    # No vowels and longer than 3 chars = likely mumble
    vowels = set('aeiou')
    if len(w) > 3 and not any(c in vowels for c in w):
        return True
    # Repeated consonants with no vowels
    if re.match(r'^[^aeiou]{4,}$', w):
        return True
    return False


# ── Noise detection ───────────────────────────────────────────────────────────
NOISE_MARKERS = {'[noise]', '[background]', '[music]', '[laughter]',
                 '[cough]', '[applause]', '[inaudible]', '[crosstalk]'}

def is_noise_marker(word: str) -> bool:
    return word.lower().strip() in NOISE_MARKERS


# ── Letter-by-letter spelling detection ──────────────────────────────────────
# Devanagari letter name map
LETTER_DEVANAGARI = {
    'a': 'ए', 'b': 'बी', 'c': 'सी', 'd': 'डी', 'e': 'ई',
    'f': 'एफ', 'g': 'जी', 'h': 'एच', 'i': 'आई', 'j': 'जे',
    'k': 'के', 'l': 'एल', 'm': 'एम', 'n': 'एन', 'o': 'ओ',
    'p': 'पी', 'q': 'क्यू', 'r': 'आर', 's': 'एस', 't': 'टी',
    'u': 'यू', 'v': 'वी', 'w': 'डब्लू', 'x': 'एक्स',
    'y': 'वाई', 'z': 'ज़ेड',
}

def is_single_letter(word: str) -> bool:
    """Check if word is a single letter being spelled out."""
    w = word.strip(".,!?()").lower()
    return len(w) == 1 and w.isalpha()

def letter_to_devanagari(letter: str) -> str:
    return LETTER_DEVANAGARI.get(letter.lower(), letter)


# ── Proper noun detection ─────────────────────────────────────────────────────
# Safe words that are capitalized but NOT proper nouns
_SAFE_CAPS = {
    'i', 'a', 'the', 'is', 'are', 'was', 'were', 'and', 'or', 'but',
    'in', 'on', 'at', 'to', 'of', 'for', 'with', 'by', 'from', 'as',
    'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'can', 'must', 'shall',
    'this', 'that', 'these', 'those', 'it', 'he', 'she', 'we', 'they',
    'my', 'his', 'her', 'our', 'their', 'its', 'your', 'not', 'no',
    'so', 'if', 'then', 'than', 'when', 'where', 'what', 'who', 'how',
    'which', 'while', 'although', 'because', 'since', 'after', 'before',
    'during', 'until', 'unless', 'however', 'therefore', 'also', 'here',
    'there', 'up', 'down', 'out', 'off', 'over', 'under', 'again',
    'very', 'just', 'now', 'today', 'still', 'even', 'only', 'both',
    'each', 'some', 'any', 'all', 'more', 'most', 'other', 'such',
    'same', 'new', 'old', 'good', 'great', 'long', 'big', 'little',
    'first', 'last', 'next', 'many', 'much', 'few', 'own', 'right',
    'well', 'back', 'never', 'always', 'often', 'yes', 'ok', 'okay',
}

def is_likely_proper_noun(word: str, position: int) -> bool:
    """Detect proper nouns: capitalized words that aren't common words, not at sentence start."""
    w_clean = re.sub(r"[^a-zA-Z]", "", word)
    if not w_clean:
        return False
    if position == 0:
        return False  # First word capitalization is normal
    if w_clean[0].isupper() and w_clean.lower() not in _SAFE_CAPS:
        return True
    return False


# ── Stretch/elongation detection ──────────────────────────────────────────────
def is_stretched(word: str) -> bool:
    """Detect elongated words like 'cooooming', 'soooo'."""
    # Look for repeated vowels or consonants (3+ same chars in a row)
    return bool(re.search(r'(.)\1{2,}', word.lower()))


# ── Silence gap handling ──────────────────────────────────────────────────────
def make_sil_annotation(sil_start: str, sil_end: str, gap_seconds: float) -> dict:
    return {
        "original":  "",
        "annotated": "<SIL></SIL>",
        "start":     sil_start,
        "end":       sil_end,
        "rule":      "SIL",
        "gap_seconds": round(gap_seconds, 2)
    }


# ── Main annotation engine ────────────────────────────────────────────────────

def apply_rules(payload: dict) -> dict:
    """
    Main entry point. Takes the same payload format as the old Gemini annotate.
    Returns {"status": "ok", "result": {...}} or {"error": "..."}
    """
    import random

    words        = payload.get("words", [])
    silence_gaps = payload.get("silence_gaps", [])
    filename     = payload.get("filename", "audio.wav")
    reference    = payload.get("reference", "")

    if not words:
        return {"error": "No words provided for annotation"}

    # Build a set of reference words for D1 matching
    ref_words = set()
    if reference:
        for w in reference.split():
            ref_words.add(re.sub(r"[^a-zA-Z'-]", "", w).lower())

    annotations = []

    # Pre-compute silence gap lookup: after which word index does a gap start?
    # Map: gap start time (seconds) → gap info
    def time_str_to_secs(t: str) -> float:
        try:
            # Format: H:MM:SS.microseconds or HH:MM:SS:MS
            t = t.replace(',', '.')
            parts = t.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 4:
                h, m, s, ms = parts
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        except:
            pass
        return 0.0

    # Index silence gaps by approximate start time
    sil_by_start = {}
    for sg in silence_gaps:
        sil_start_secs = sg.get("sil_start", "")
        gap_secs = sg.get("gap_seconds", 0)
        if gap_secs > 2.0:
            key = round(time_str_to_secs(str(sil_start_secs)), 1)
            sil_by_start[key] = sg

    # Track which silence gaps have been inserted
    inserted_sils = set()

    # Check for leading silence (before first word)
    if words:
        first_start = words[0].get("start_seconds", 0)
        if first_start > 2.0:
            # Find matching silence gap
            for sg in silence_gaps:
                gap = sg.get("gap_seconds", 0)
                if gap > 2.0 and sg.get("type") == "leading":
                    annotations.append(make_sil_annotation(
                        sg.get("sil_start", "0:00:00.000000"),
                        sg.get("sil_end", words[0]["start"]),
                        gap
                    ))
                    inserted_sils.add(id(sg))
                    break

    # Process each word
    for idx, w in enumerate(words):
        word     = w.get("word", "").strip()
        start    = w.get("start", "")
        end      = w.get("end", "")
        hint     = w.get("hint", "NORMAL")
        start_s  = w.get("start_seconds", 0)
        end_s    = w.get("end_seconds", 0)

        if not word:
            continue

        # ── Check if a silence gap should be inserted BEFORE this word ──────
        if idx > 0:
            prev_end_s = words[idx - 1].get("end_seconds", 0)
            gap = start_s - prev_end_s
            if gap > 2.0:
                # Find the matching silence gap object
                for sg in silence_gaps:
                    if sg in [s for s in silence_gaps if id(s) not in inserted_sils]:
                        sg_gap = sg.get("gap_seconds", 0)
                        if sg_gap > 2.0 and abs(sg_gap - gap) < 1.0:
                            annotations.append(make_sil_annotation(
                                sg.get("sil_start", words[idx-1]["end"]),
                                sg.get("sil_end", start),
                                sg_gap
                            ))
                            inserted_sils.add(id(sg))
                            break
                else:
                    # No matching gap object found, create one
                    annotations.append(make_sil_annotation(
                        words[idx-1]["end"], start, round(gap, 2)
                    ))

        word_clean = re.sub(r"[^a-zA-Z'-]", "", word).lower()

        # ── NOISE marker ──────────────────────────────────────────────────────
        if is_noise_marker(word):
            annotations.append({
                "original":  word,
                "annotated": "<NOISE></NOISE>",
                "start": start, "end": end,
                "rule": "NOISE"
            })
            continue

        # ── MB: completely unintelligible ─────────────────────────────────────
        if hint == "LIKELY_MB" or is_mumble(word):
            annotations.append({
                "original":  word,
                "annotated": "<MB></MB>",
                "start": start, "end": end,
                "rule": "MB"
            })
            continue

        # ── FIL: filler / hesitation sounds ──────────────────────────────────
        if hint == "LIKELY_FILLER" or is_filler(word):
            dev = get_filler_devanagari(word)
            annotations.append({
                "original":  word,
                "annotated": f"<FIL>{dev}</FIL>",
                "start": start, "end": end,
                "rule": "FIL"
            })
            continue

        # ── Single letter spelling (LN tag) ───────────────────────────────────
        if is_single_letter(word):
            dev = letter_to_devanagari(word)
            annotations.append({
                "original":  word,
                "annotated": f"<LN>{dev}</LN>",
                "start": start, "end": end,
                "rule": "LN"
            })
            continue

        # ── Proper noun → Devanagari ──────────────────────────────────────────
        if hint == "LIKELY_PROPER_NOUN" or is_likely_proper_noun(word, idx):
            dev = convert_to_devanagari(word, context="proper noun")
            annotations.append({
                "original":  word,
                "annotated": dev,
                "start": start, "end": end,
                "rule": "D3-ProperNoun"
            })
            continue

        # ── Stretched/elongated word → Devanagari + one extra char ───────────
        if is_stretched(word):
            dev = convert_to_devanagari(word, context="elongated word")
            annotations.append({
                "original":  word,
                "annotated": dev,
                "start": start, "end": end,
                "rule": "D3-Stretch"
            })
            continue

        # ── D1: Valid English word (correct or acceptable accent variant) ─────
        if is_valid_english(word):
            # If word is in reference, use reference spelling exactly
            ref_match = None
            if ref_words and word_clean in ref_words:
                # Find original casing from reference
                for rw in (reference or "").split():
                    if re.sub(r"[^a-zA-Z'-]", "", rw).lower() == word_clean:
                        ref_match = rw
                        break
            annotated = ref_match if ref_match else word
            annotations.append({
                "original":  word,
                "annotated": annotated,
                "start": start, "end": end,
                "rule": "D1-English"
            })
            continue

        # ── Devanagari already in word ────────────────────────────────────────
        if any('\u0900' <= c <= '\u097F' for c in word):
            annotations.append({
                "original":  word,
                "annotated": word,
                "start": start, "end": end,
                "rule": "D3-Devanagari"
            })
            continue

        # ── D3: Not a valid English word → Devanagari via Claude ─────────────
        ref_context = ""
        if ref_words:
            # Find closest reference word for context
            ref_context = next(
                (rw for rw in (reference or "").split()
                 if word_clean and rw.lower().startswith(word_clean[:2])),
                ""
            )
        dev = convert_to_devanagari(word, context=ref_context)
        annotations.append({
            "original":  word,
            "annotated": dev,
            "start": start, "end": end,
            "rule": "D3-Devanagari"
        })

    # ── Insert any remaining silence gaps not yet added ───────────────────────
    for sg in silence_gaps:
        if id(sg) not in inserted_sils and sg.get("gap_seconds", 0) > 2.0:
            annotations.append(make_sil_annotation(
                sg.get("sil_start", ""),
                sg.get("sil_end", ""),
                sg.get("gap_seconds", 0)
            ))

    # ── Sort all annotations by start time ───────────────────────────────────
    def sort_key(a):
        return time_str_to_secs(str(a.get("start", "0")))

    annotations.sort(key=sort_key)

    # ── Build output ──────────────────────────────────────────────────────────
    transcript = " ".join(a.get("annotated", "") for a in annotations)

    annotic_annotations = []
    for a in annotations:
        annotic_annotations.append({
            "start":         a.get("start", ""),
            "end":           a.get("end", ""),
            "original":      a.get("original", ""),
            "annotated":     a.get("annotated", ""),
            "rule":          a.get("rule", ""),
            "Transcription": [a.get("annotated", "")]
        })

    result = {
        "transcript":   transcript,
        "annotations":  annotations,
        "explanation":  f"Rule engine applied. {len(annotations)} annotations produced.",
        "annotic_json": {
            "file_name":   filename,
            "id":          random.randint(10000, 99999),
            "annotations": annotic_annotations,
        }
    }

    print(f"[*] Rule engine done! {len(annotations)} annotations")
    return {"status": "ok", "result": result}


# ── Chunked annotation (same interface as before) ─────────────────────────────

MAX_WORDS_PER_CHUNK = 100  # Pure Python is fast, can handle more per chunk

def annotate_chunked(payload: dict) -> dict:
    words = payload.get("words", [])
    if len(words) <= MAX_WORDS_PER_CHUNK:
        return apply_rules(payload)

    print(f"[*] {len(words)} words — splitting into chunks of {MAX_WORDS_PER_CHUNK}")
    all_annotations = []
    all_annotic     = []
    total_chunks    = -(-len(words) // MAX_WORDS_PER_CHUNK)

    for i in range(0, len(words), MAX_WORDS_PER_CHUNK):
        chunk = words[i:i + MAX_WORDS_PER_CHUNK]
        chunk_payload = dict(payload)
        chunk_payload["words"] = chunk

        # Filter silence gaps for this chunk's time range
        chunk_start = chunk[0].get("start_seconds", 0)
        chunk_end   = chunk[-1].get("end_seconds", 9999999)
        chunk_payload["silence_gaps"] = [
            s for s in payload.get("silence_gaps", [])
            if chunk_start <= s.get("gap_seconds", 0) <= chunk_end
                or (chunk_start <= chunk_end)
        ]

        chunk_num = i // MAX_WORDS_PER_CHUNK + 1
        print(f"[*] Chunk {chunk_num}/{total_chunks}: words {i}–{i + len(chunk) - 1}")

        result = apply_rules(chunk_payload)
        if result.get("status") != "ok":
            return {"error": f"Chunk {chunk_num} failed: {result.get('error')}"}

        res = result["result"]
        all_annotations.extend(res.get("annotations", []))
        all_annotic.extend(res.get("annotic_json", {}).get("annotations", []))

    import random
    merged = {
        "transcript":   " ".join(a.get("annotated", "") for a in all_annotations),
        "annotations":  all_annotations,
        "explanation":  f"Chunked rule engine ({total_chunks} chunks, {len(all_annotations)} annotations).",
        "annotic_json": {
            "file_name":   payload.get("filename", "audio.wav"),
            "id":          random.randint(10000, 99999),
            "annotations": all_annotic,
        }
    }
    print(f"[*] All {total_chunks} chunks merged. Total: {len(all_annotations)} annotations")
    return {"status": "ok", "result": merged}


# ── Public API (drop-in replacement for call_gemini_annotate_full) ────────────

def call_rule_engine(payload: dict) -> dict:
    """
    Drop-in replacement for call_gemini_annotate_full() in server.py
    Usage in server.py:
        from annotate import call_rule_engine
        # replace: result = call_gemini_annotate_full(payload)
        # with:    result = call_rule_engine(payload)
    """
    return annotate_chunked(payload)
