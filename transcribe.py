import sys
import json
import os
import re


def fmt(secs):
    # Exact PDF format: 0:00:00.519350
    secs = max(0.0, float(secs))
    h  = int(secs // 3600)
    m  = int((secs % 3600) // 60)
    s  = int(secs % 60)
    us = int(round((secs - int(secs)) * 1_000_000))
    return f"{h}:{m:02d}:{s:02d}.{us:06d}"


# ─────────────────────────────────────────────
# Comprehensive English dictionary check
# ─────────────────────────────────────────────
COMMON_ENGLISH_WORDS = {
    # Articles / determiners
    'the','a','an','this','that','these','those','some','any','all','both',
    'each','every','few','more','most','much','many','other','such','no',
    # Pronouns
    'i','you','he','she','it','we','they','me','him','her','us','them',
    'my','your','his','its','our','their','mine','yours','hers','ours','theirs',
    'myself','yourself','himself','herself','itself','ourselves','themselves',
    'who','whom','whose','which','what',
    # Conjunctions / prepositions
    'and','or','but','so','if','then','because','as','at','by','for','from',
    'in','into','of','on','out','to','up','with','about','after','before',
    'between','through','during','under','over','above','below','within',
    'without','around','along','against','across','behind','beside','beyond',
    'near','off','since','until','upon','while','although','though','unless',
    'whether','nor','yet','both','either','neither','not','also','just',
    'even','still','already','always','never','ever','often','sometimes',
    'usually','here','there','where','when','how','why',
    # Auxiliaries / modals
    'is','are','was','were','be','been','being','have','has','had','do',
    'does','did','will','would','shall','should','may','might','can','could',
    'must','need','ought',
    # Common verbs
    'go','get','give','come','take','make','know','think','see','look',
    'want','use','find','tell','ask','seem','feel','try','leave','call',
    'keep','let','begin','show','hear','play','run','move','live','believe',
    'hold','bring','happen','write','provide','sit','stand','lose','pay',
    'meet','include','continue','set','learn','change','lead','understand',
    'watch','follow','stop','create','speak','read','spend','grow','open',
    'walk','talk','eat','drink','sleep','work','help','turn','start','might',
    'put','mean','become','leave','show','win','offer','remember','love',
    'consider','appear','buy','wait','serve','die','send','expect','build',
    'stay','fall','cut','reach','kill','remain','suggest','raise','pass',
    'sell','require','report','decide','pull','break','carry',
    # Common nouns
    'time','year','people','way','day','man','woman','child','world','life',
    'hand','part','place','case','week','company','system','program','question',
    'government','number','night','point','home','water','room','mother',
    'area','money','story','fact','month','lot','right','study','book',
    'eye','job','word','business','issue','side','kind','head','house',
    'service','friend','father','power','hour','game','line','end','among',
    'state','city','community','name','president','team','minute','idea',
    'body','information','back','parent','face','others','level','office',
    'door','health','person','art','war','history','party','result','change',
    'morning','reason','research','girl','guy','moment','air','teacher',
    'force','education','food','city','town','country','school','class',
    'color','colour','light','voice','music','road','car','model','list',
    'bird','fish','dog','cat','tree','flower','stone','fire','earth',
    # Common adjectives
    'good','great','new','old','first','last','long','little','own','right',
    'big','high','small','large','next','early','young','important','few',
    'public','private','real','best','free','able','open','special','hard',
    'clear','recent','sure','true','whole','easy','possible','major','human',
    'local','national','economic','political','social','different','only',
    'full','hot','cold','happy','bad','correct','wrong','short','low',
    'same','enough','far','second','third','main','central','former',
    # Common adverbs
    'very','well','back','out','up','down','now','then','just','more',
    'also','too','so','only','still','even','again','away','off','ever',
    'once','almost','most','already','around','perhaps','soon','less',
    'instead','yet','later','here','quite','simply','especially','however',
    # Numbers / quantity
    'one','two','three','four','five','six','seven','eight','nine','ten',
    'hundred','thousand','million','billion','first','second','third','half',
    # Common contractions (as heard)
    "don't","can't","won't","isn't","aren't","wasn't","weren't","hasn't",
    "haven't","hadn't","doesn't","didn't","couldn't","wouldn't","shouldn't",
    "it's","i'm","you're","he's","she's","we're","they're","i've","you've",
    "we've","they've","i'll","you'll","he'll","she'll","we'll","they'll",
    "i'd","you'd","he'd","she'd","we'd","they'd","that's","what's","who's",
    # Story / narrative words
    'king','queen','prince','princess','kingdom','palace','castle','forest',
    'river','mountain','village','farmer','merchant','soldier','wise','brave',
    'honest','kind','poor','rich','famous','once','upon','lived','called',
    'asked','said','told','came','went','saw','knew','found','gave','took',
    'came','replied','answered','decided','wanted','needed','tried','helped',
}

def is_likely_english(word):
    """Return True if the word is likely a valid English word."""
    w = word.lower().strip(".,!?;:'\"()-")
    if w in COMMON_ENGLISH_WORDS:
        return True
    # Basic heuristic: has vowels, reasonable consonant clusters
    if len(w) < 2:
        return False
    vowels = sum(1 for c in w if c in 'aeiou')
    if vowels == 0 and len(w) > 2:
        return False  # probably gibberish or consonant-only
    return True


def classify_word(word):
    """
    Classify each Whisper word to give the AI annotator strong hints.
    Returns one of:
      LIKELY_FILLER       – uh, um, aah, hmm etc.
      LIKELY_MB           – unintelligible, no vowels, gibberish
      LIKELY_NOISE_MB     – Whisper noise markers
      LIKELY_DEVANAGARI   – non-English, needs Devanagari
      LIKELY_PROPER_NOUN  – capitalised mid-sentence (possible name/place)
      NORMAL              – standard correctly-pronounced English word
    """
    w_raw  = word.strip()
    w      = w_raw.lower().strip(".,!?;:'\"()-")

    # ── Filler sounds ────────────────────────────────────────
    # IMPORTANT: 'a' (article) and 'i' (pronoun) must NEVER be fillers
    # Only multi-char hesitation sounds qualify as fillers

    # Single-char words that are REAL English — never filler
    real_single_chars = {'a', 'i', 'o'}  # 'a'=article, 'i'=pronoun variant, 'o'=interjection
    if w in real_single_chars:
        return 'NORMAL'

    fillers_exact = {
        # uh sounds — must be 2+ chars to avoid false positive
        'uh','uhh','uhhh','uhhhh',
        # um sounds
        'um','umm','ummm','ummmm',
        # aah sounds — 'aa' or longer only, NOT single 'a'
        'ahh','aah','aaah','aaaah','aaaaah',
        'aa','aaa','aaaa','aaaaa',
        # eh sounds
        'eh','ehh','ehhh',
        # er sounds
        'er','erm','errr',
        # hmm sounds
        'hmm','hm','hmmm','hmmmm',
        # haan/han
        'haan','han',
        # oh/ooh — only when clearly hesitation (2+ chars)
        'ohh','ooh','oooh',
        # mm
        'mm','mmm','mmmm',
    }
    if w in fillers_exact:
        return 'LIKELY_FILLER'

    # Repeated vowel pattern — must be 2+ chars (exclude single 'a', 'u', 'e', 'o')
    if len(w) >= 2 and re.fullmatch(r'(a{2,}h*|u{2,}h*|e{2,}h*|o{2,}h*|m{2,}|h+m+|h+a+n*)', w):
        return 'LIKELY_FILLER'

    # ── Whisper noise/unintelligible markers ─────────────────
    noise_markers = [
        '[inaudible]','[unintelligible]','[noise]','[music]',
        '[applause]','[laughter]','[unclear]','[crosstalk]',
        '[background]','[static]','[beep]',
    ]
    if any(x in w for x in noise_markers):
        return 'LIKELY_NOISE_MB'

    # ── Gibberish / mumble: too many consonants, no vowels ───
    vowels = sum(1 for c in w if c in 'aeiou')
    if len(w) > 3 and vowels == 0:
        return 'LIKELY_MB'
    if len(w) > 5 and vowels / len(w) < 0.1:
        return 'LIKELY_MB'

    # ── Proper noun hint: capitalised & not common word ──────
    # A word starting with capital that's not at sentence start
    if w_raw and w_raw[0].isupper() and w not in COMMON_ENGLISH_WORDS:
        # Could be proper noun (name, place, animal)
        return 'LIKELY_PROPER_NOUN'

    # ── Non-English characters (already Devanagari from Whisper)
    if any('\u0900' <= c <= '\u097F' for c in w_raw):
        return 'LIKELY_DEVANAGARI'

    return 'NORMAL'


def detect_letter_spelling(words_list, idx):
    """
    Detect if consecutive single letters are being spelled out.
    Returns True if the word at idx looks like a letter name being read.
    Heuristic: single letter (a-z) surrounded by other single letters.
    """
    w = words_list[idx]['word'].lower().strip(".,!?;:'\"()-")
    if len(w) != 1 and w not in ['bee','see','dee','ee','eff','gee','aitch',
                                   'jay','kay','el','em','en','pee','que',
                                   'ar','ess','tee','vee','doubleyou','ex',
                                   'why','zed','zee']:
        return False
    # Check neighbours
    neighbours = []
    if idx > 0:
        neighbours.append(words_list[idx-1]['word'].lower().strip(".,!?;:'\"()-"))
    if idx < len(words_list)-1:
        neighbours.append(words_list[idx+1]['word'].lower().strip(".,!?;:'\"()-"))
    for n in neighbours:
        if len(n) == 1 and n.isalpha():
            return True
    return False


def transcribe(audio_path):
    try:
        import whisper
    except ImportError:
        import subprocess
        print("[*] Installing whisper...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "openai-whisper", "--quiet"])
        import whisper

    print("[*] Loading Whisper small model...")
    model = whisper.load_model("small")

    print("[*] Transcribing:", audio_path)
    print("[*] Please wait — long audio may take several minutes...")

    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        verbose=False,
        condition_on_previous_text=True,
        temperature=0.0
    )

    # ── Build word list with timestamps and classification hints ──
    words = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            word = w["word"].strip()
            if not word:
                continue
            start = float(w["start"])
            end   = float(w["end"])
            hint  = classify_word(word)
            words.append({
                "word":          word,
                "start":         fmt(start),
                "end":           fmt(end),
                "start_seconds": round(start, 6),
                "end_seconds":   round(end, 6),
                "hint":          hint,
                "is_english":    is_likely_english(word),
            })

    # ── Post-process: detect letter-spelling sequences ────────
    for i, w in enumerate(words):
        if detect_letter_spelling(words, i):
            words[i]['hint'] = 'LIKELY_LETTER_SPELLING'

    # ── Detect sub-lexical pauses (very short words close together) ──
    # Words spoken with intra-word pauses — annotate gap info
    sublex_pauses = []
    for i in range(len(words) - 1):
        gap = words[i+1]["start_seconds"] - words[i]["end_seconds"]
        if 0.05 < gap <= 2.0:
            # Small gap — could be intra-word pause (sub-lexical)
            sublex_pauses.append({
                "between": [words[i]["word"], words[i+1]["word"]],
                "gap_seconds": round(gap, 4),
                "after_end":   words[i]["end"],
                "before_start": words[i+1]["start"],
            })

    # ── Detect leading silence ────────────────────────────────
    leading_silence = None
    if words and words[0]["start_seconds"] > 2.0:
        leading_silence = {
            "gap_seconds": round(words[0]["start_seconds"], 6),
            "sil_start":   fmt(0),
            "sil_end":     words[0]["start"],
            "type":        "leading"
        }

    # ── Detect silence gaps > 2 seconds ──────────────────────
    silence_gaps = []
    for i in range(len(words) - 1):
        gap = words[i+1]["start_seconds"] - words[i]["end_seconds"]
        if gap > 2.0:
            silence_gaps.append({
                "after_word":  words[i]["word"],
                "before_word": words[i+1]["word"],
                "gap_seconds": round(gap, 6),
                "sil_start":   words[i]["end"],
                "sil_end":     words[i+1]["start"]
            })

    if leading_silence:
        silence_gaps.insert(0, leading_silence)

    # ── Summary stats ─────────────────────────────────────────
    hint_counts = {}
    for w in words:
        hint_counts[w['hint']] = hint_counts.get(w['hint'], 0) + 1

    output = {
        "audio_file":      os.path.basename(audio_path),
        "full_transcript": result["text"].strip(),
        "words":           words,
        "silence_gaps":    silence_gaps,
        "leading_silence": leading_silence,
        "sublex_pauses":   sublex_pauses,
        "hint_summary":    hint_counts,
    }

    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "transcript_output.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── Console summary ───────────────────────────────────────
    fillers       = hint_counts.get('LIKELY_FILLER', 0)
    mb_words      = hint_counts.get('LIKELY_MB', 0) + hint_counts.get('LIKELY_NOISE_MB', 0)
    proper_nouns  = hint_counts.get('LIKELY_PROPER_NOUN', 0)
    letter_spell  = hint_counts.get('LIKELY_LETTER_SPELLING', 0)

    print(f"[*] Done! {len(words)} words transcribed.")
    if words:
        print(f"[*] First: '{words[0]['word']}'  {words[0]['start']} -> {words[0]['end']}")
        print(f"[*] Last:  '{words[-1]['word']}'  {words[-1]['start']} -> {words[-1]['end']}")
    if silence_gaps:
        print(f"[*] Silence gaps > 2s : {len(silence_gaps)}")
        for s in silence_gaps:
            print(f"    {s['gap_seconds']}s  '{s.get('after_word','START')}' -> '{s.get('before_word','')}'")
    if fillers:
        print(f"[*] Likely fillers detected     : {fillers}")
    if mb_words:
        print(f"[*] Likely mumbling/noise       : {mb_words}")
    if proper_nouns:
        print(f"[*] Likely proper nouns         : {proper_nouns}")
    if letter_spell:
        print(f"[*] Likely letter-spelling      : {letter_spell}")
    print(f"[*] Saved: {out_path}")
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <audio_file>")
        sys.exit(1)
    transcribe(sys.argv[1])
