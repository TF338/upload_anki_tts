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


def build_id_mapping():
    """Build a mapping of custom IDs to Anki note IDs for all Chinese cards"""
    existing_notes = invoke_anki("findNotes", {"query": f"note:Chinese"})
    notes_info = invoke_anki("notesInfo", {"notes": existing_notes})

    id_to_note = {}
    for note in notes_info:
        custom_id = note['fields'].get('ID', {}).get('value', '')
        if custom_id:
            id_to_note[custom_id] = note['noteId']

    return id_to_note

def find_existing_note_by_content(chinese_text, english_text, deck_name, chinese_field, english_field):
    """Find existing note by Chinese and English content"""
    # Query for notes with the same Chinese text
    chinese_query = f'"{chinese_field}:{chinese_text}"'
    existing_notes = invoke_anki("findNotes", {"query": chinese_query})

    if not existing_notes:
        return None

    # Check if any of the found notes also match the English text and are in the right deck
    notes_info = invoke_anki("notesInfo", {"notes": existing_notes})
    for note in notes_info:
        note_english = note['fields'].get(english_field, {}).get('value', '')
        if note_english.strip() == english_text.strip():
            return note['noteId']

    return None


def update_or_create_card(card_data, deck_name, model_name, chinese_field, english_field, pinyin_field, sound_field):
    """
    Update existing card or create new one based on content matching.
    card_data should be a dictionary with:
    - id: unique identifier
    - chinese: Chinese text
    - pinyin: Pinyin text
    - english: English translation
    - tags: list of tags
    - audio_filename: audio filename (optional)
    """
    card_id = card_data['id']
    chinese_text = card_data['chinese']
    english_text = card_data['english']

    # Try to find existing note by content
    note_id = find_existing_note_by_content(chinese_text, english_text, deck_name, chinese_field, english_field)

    # Build fields dictionary
    fields = {
        chinese_field: chinese_text,
        english_field: english_text,
        pinyin_field: card_data.get('pinyin', ''),
        "ID": card_id  # Add ID field for future reference
    }

    # Add sound field if audio filename exists
    if card_data.get('audio_filename'):
        fields[sound_field] = "[sound:" + card_data['audio_filename'] + "]"

    if note_id:
        # Update existing card
        invoke_anki("updateNote", {
            "note": {
                "id": note_id,
                "fields": fields,
                "tags": card_data['tags']
            }
        })
        return note_id, f"Updated existing card: {card_id}"
    else:
        # Create new card
        note = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "tags": card_data['tags'] or []
        }

        new_note_id = invoke_anki("addNote", {"note": note})
        return new_note_id, f"Created new card: {card_id} (Note ID: {new_note_id})"

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

        # Check if we need to generate audio
        needs_audio = not it.get("audio_filename")

        if needs_audio:
            fname = safe_filename(item_id + "_" + chinese[:20])  # deterministic filename
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

            it["audio_filename"] = fname
        else:
            fname = it["audio_filename"]
            print(f"[SKIP] item {item_id} already has audio: {fname}")

        # Update or create the card
        card_data = {
            "id": item_id,
            "chinese": chinese,
            "english": english,
            "pinyin": pinyin,
            "tags": tags,
            "audio_filename": fname
        }

        if dry:
            print(f"[DRY] would update/create card in deck '{deck_name}' using model '{model_name}'")
            it["anki_note_id"] = f"dry_run_{item_id}"
        else:
            try:
                note_id, message = update_or_create_card(
                    card_data, deck_name, model_name, chinese_field, english_field,
                    pinyin_field, sound_field
                )
                print(f"[OK] {message}")
                it["anki_note_id"] = note_id
            except Exception as e:
                print(f"[ERROR] failed to create/update note for {item_id}: {e}")
                continue

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
    p.add_argument("--dry", action="store_true",
                   help="Dry run: do not upload to Anki or modify original JSON (writes .dryrun.json).")
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
    temp_dir = project_root / cfg.get("temp_dir", None)
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