#!/usr/bin/env python3

import base64
import json
import time
import tempfile
import yaml
from pathlib import Path

import requests

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except Exception:
    GTTS_AVAILABLE = False

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
DEFAULT_TTS_LANG = "zh-CN"

def load_config(cfg_path):
    p = Path(cfg_path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yml", ".yaml"):
        return yaml.safe_load(text)
    else:
        return json.loads(text)

def load_input_jsons(input_dir):
    in_path = Path(input_dir)
    if not in_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    files = sorted(in_path.glob("*.json"))
    combined = []
    provenance = []  # list of (src_path, start_index, end_index)
    idx = 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise RuntimeError(f"Input JSON {f} must be a list of objects.")
        start = idx
        combined.extend(data)
        idx += len(data)
        end = idx
        provenance.append((str(f), start, end))
    return combined, provenance

def write_back_results(items, provenance, temp_dir, dry=False):
    """Split combined items back into original files and write updated JSONs (or .dryrun.json)."""
    for src, start, end in provenance:
        piece = items[start:end]
        p = Path(temp_dir) / "out"
        if dry:
            out = p.with_suffix(".dryrun.json")
        else:
            out = p
        if not dry:
            backup = p.with_suffix(".bak.json")
            if p.exists():
                p.rename(backup)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(piece, fh, ensure_ascii=False, indent=2)
        print(f"[SAVE] wrote {out}")

def invoke_anki(action, params=None, timeout=60):
    payload = {"action": action, "version": 6}
    if params is not None:
        payload["params"] = params
    r = requests.post(ANKI_CONNECT_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    res = r.json()
    if res.get("error") is not None:
        raise Exception(f"AnkiConnect error: {res['error']}")
    return res.get("result")

def tts_with_gtts(text, lang=DEFAULT_TTS_LANG, filepath=None, slow=False):
    """Generate mp3 using gTTS and save to filepath. Returns filepath."""
    if not GTTS_AVAILABLE:
        raise RuntimeError("gTTS not available (pip install gTTS) - cannot use this function.")
    tts = gTTS(text, lang=lang, slow=slow)
    tts.save(str(filepath))
    return filepath

def tts_with_google_translate_endpoint(text, lang=DEFAULT_TTS_LANG, filepath=None):
    """
    Fallback method (may break if Google changes endpoint or rate-limit).
    We will do a simple request to translate_tts endpoint. Note: usage may be unreliable.
    """
    # This endpoint often works for small requests:
    base = "https://translate.google.com/translate_tts"
    params = {
        "ie": "UTF-8",
        "q": text,
        "tl": lang,
        "client": "tw-ob",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36",
        "Referer": "https://translate.google.com/",
    }
    r = requests.get(base, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    with open(filepath, "wb") as fh:
        fh.write(r.content)
    return filepath

def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)

def safe_filename(s):
    """Return a safe filename for storing in Anki media folder"""
    import hashlib
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]
    short = "".join([c for c in s if c.isalnum()])[:12]
    return f"tts_{short}_{h}.mp3"

def store_media_bytes_to_anki(filename, data_bytes):
    b64 = base64.b64encode(data_bytes).decode("utf-8")
    invoke_anki("storeMediaFile", {"filename": filename, "data": b64})
    return filename

def create_anki_note(deck_name, model_name, chinese_field_name, english_field_name, pinyin_field_name, sound_field_name, chinese_text, english_text, pinyin_text, audio_filename, tags):
    note = {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": {
            chinese_field_name: chinese_text,
            english_field_name: english_text,
            pinyin_field_name: pinyin_text,
            sound_field_name: "[sound:" + audio_filename + "]"
        },
        "options": {
            "allowDuplicate": False
        },
        "tags": tags or []
    }
    res = invoke_anki("addNote", {"note": note})
    return res  # returns note id or None

def process_items(json_path, deck_name, model_name, chinese_field, english_field, pinyin_field, sound_field,
                  dry=False, tts_lang=DEFAULT_TTS_LANG, temp_media_dir=None, rate_sleep=0.4):
    with open(json_path, "r", encoding="utf-8") as fh:
        items = json.load(fh)

    if not isinstance(items, list):
        raise RuntimeError("Input JSON must be a list of objects (one item per sentence).")

    tempdir = Path(temp_media_dir) if temp_media_dir else Path(tempfile.gettempdir()) / "anki_tts_temp"
    ensure_dir(tempdir)

    updated = False
    for idx, it in enumerate(items):
        item_id = it.get("id") or f"idx{idx}"
        chinese = it.get("chinese")
        english = it.get("english", "")
        pinyin = it.get("pinyin", "")
        tags = it.get("tags", [])

        if not chinese:
            print(f"[SKIP] item {item_id} has no 'chinese' field.")
            continue

        if it.get("audio_filename") and it.get("anki_note_id"):
            print(f"[SKIP] item {item_id} already processed ({it.get('audio_filename')}).")
            continue

        fname = safe_filename(item_id + "_" + chinese[:20]) #deterministic filename
        local_mp3 = tempdir / fname

        try:
            if GTTS_AVAILABLE:
                print(f"[TTS] Using gTTS for item {item_id} ...")
                tts_with_gtts(chinese, lang=tts_lang, filepath=local_mp3)
            else:
                print(f"[TTS] gTTS not available; trying direct Google Translate endpoint for item {item_id} ...")
                tts_with_google_translate_endpoint(chinese, lang=tts_lang, filepath=local_mp3)
        except Exception as e:
            print(f"[ERROR] TTS failed for item {item_id}: {e}")
            continue

        with open(local_mp3, "rb") as fh:
            data = fh.read()

        print(f"[UPLOAD] uploading {fname} to Anki media ...")
        if dry:
            print(f"[DRY] would store media as {fname} (size {len(data)} bytes)")
        else:
            try:
                store_media_bytes_to_anki(fname, data)
            except Exception as e:
                print(f"[ERROR] failed to store media for {item_id}: {e}")
                continue

        if dry:
            print(f"[DRY] would create note in deck '{deck_name}' using model '{model_name}', fields: {chinese_field}, {english_field}")
        else:
            try:
                note_id = create_anki_note(deck_name, model_name, chinese_field, english_field, pinyin_field, sound_field, chinese, english, pinyin, fname, tags)
                print(f"[OK] added note id {note_id} for item {item_id}")
                it["anki_note_id"] = note_id
            except Exception as e:
                print(f"[ERROR] failed to create note for {item_id}: {e}")
                continue

        it["audio_filename"] = fname
        updated = True

        time.sleep(rate_sleep)

    if updated and not dry:
        backup_path = Path(json_path).with_suffix(".bak.json")
        print(f"[SAVE] backing up original JSON to {backup_path}")
        Path(json_path).rename(backup_path)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
        print(f"[SAVE] updated JSON written to {json_path}")
    elif updated and dry:
        out_path = Path(json_path).with_suffix(".dryrun.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
        print(f"[DRY] wrote dry-run JSON to {out_path}")

    print("Done.")

def main():
    import argparse
    p = argparse.ArgumentParser(description="Generate TTS for Chinese sentences and upload to Anki via AnkiConnect.")
    p.add_argument("--dry", action="store_true", help="Dry run: do not upload to Anki or modify original JSON (writes .dryrun.json).")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    cfg_path = project_root / "config.yml"
    input_dir = project_root / "input"

    cfg = load_config(cfg_path)
    deck_name = cfg.get("deck")
    model_name = cfg.get("model")
    chinese_field = cfg.get("field_chinese")
    english_field = cfg.get("field_english")
    pinyin_field = cfg.get("field_pinyin")
    sound_field = cfg.get("field_sound")
    tts_lang = cfg.get("tts_lang", DEFAULT_TTS_LANG)
    temp_dir =project_root /  cfg.get("temp_dir", None)
    rate_sleep = float(cfg.get("rate_sleep", 0.4))
    default_tags = cfg.get("default_tags", ["generated", "hsk4"])

    if not all([deck_name, model_name, chinese_field, english_field]):
        raise RuntimeError("Config missing required keys: deck, model, field_chinese, field_english")

    print("Loaded config:", cfg_path)
    print("Deck:", deck_name, "Model:", model_name, "Chinese field:", chinese_field, "English field:", english_field)
    print("Input dir:", input_dir, "Dry run:", args.dry)

    items, provenance = load_input_jsons(input_dir)
    print(f"Loaded {len(items)} items from {len(provenance)} files.")

    for it in items:
        if "tags" not in it or not isinstance(it["tags"], list):
            it["tags"] = list(default_tags)

    if not temp_dir.exists():
        temp_dir.mkdir(parents=True)
    else:
        for item in temp_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                import shutil
                shutil.rmtree(item)

    temp_combined = temp_dir / "__combined_tmp_for_processing.json"
    with open(temp_combined, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)

    try:
        process_items(
            str(temp_combined),
            deck_name,
            model_name,
            chinese_field,
            english_field,
            pinyin_field,
            sound_field,
            dry=args.dry,
            tts_lang=tts_lang,
            temp_media_dir=temp_dir,
            rate_sleep=rate_sleep,
        )
        processed = json.loads(temp_combined.read_text(encoding="utf-8"))
        write_back_results(processed, provenance, temp_dir, dry=args.dry)
    finally:
        try:
            if temp_combined.exists():
                temp_combined.unlink()
        except Exception:
            pass

if __name__ == "__main__":
    main()
