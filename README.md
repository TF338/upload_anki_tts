# Anki Chinese TTS Card Generator

This Python script automates the creation and updating of **Chinese Anki flashcards** by reading sentence data from JSON files, generating **TTS (text-to-speech)** audio, and uploading everything to **Anki via AnkiConnect**.

It’s especially useful for building HSK-style decks or custom sentence decks — including ones generated automatically by a large language model (LLM) such as ChatGPT.

---

## Features

- Load and combine JSON sentence files  
- Generate TTS audio (using `gTTS` or a fallback Google Translate endpoint)  
- Upload MP3s directly into Anki’s media folder  
- Create or update Anki cards through **AnkiConnect**  
- Backup and dry-run modes to protect data  
- Fully configurable via `config.yml`

---

## Requirements

- **Python 3.8+**  
- **Anki** running locally with the **AnkiConnect** add-on  
    [Download AnkiConnect](https://ankiweb.net/shared/info/2055492159)  
- **Dependencies:**
```
pip install requests pyyaml gTTS
```

---

## Configuration (`config.yml`)

Example:
```
deck: "Chinese Sentences"
model: "Chinese Model"
field_chinese: "Chinese"
field_english: "English"
field_pinyin: "Pinyin"
field_sound: "Audio"
tts_lang: "zh-CN"
temp_dir: "temp_media"
rate_sleep: 0.4
default_tags: ["generated", "hsk4"]
```

---

## Generating Input Sentences with an LLM

You can use an AI model (like ChatGPT or GPT-5) to automatically create input JSONs for this tool.  
Here’s an example **prompt** you can paste into your LLM:

```
generate me a json list wit the following structure:

  {"id":"058_稍微_3","chinese":"这个菜稍微加点盐会更好吃。","pinyin":"Zhège cài shāowēi jiā diǎn yán huì gèng hǎochī.","english":"This dish would taste better with a little more salt.","tags":["generated","hsk4","word-稍微"]},
 5 sentences per word. but only use hsk 1 to hsk 4 words. you can reference this list of words to see which words are approved:
 https://hsk.academy/en/hsk-1-vocabulary-list
 https://hsk.academy/en/hsk-2-vocabulary-list
 https://hsk.academy/en/hsk-3-vocabulary-list
 https://hsk.academy/en/hsk-4-vocabulary-list

the Chinese words i want you to generate 5  examples for are: 
故意
否则
可惜
```

A model will output something like:

```
[
  {"id":"001_故意_1","chinese":"他故意不告诉我。","pinyin":"Tā gùyì bù gàosù wǒ.","english":"He didn’t tell me on purpose.","tags":["generated","hsk4","word-故意"]},
  {"id":"001_故意_2","chinese":"你是不是故意迟到的？","pinyin":"Nǐ shì bù shì gùyì chídào de?","english":"Did you come late on purpose?","tags":["generated","hsk4","word-故意"]},
  {"id":"002_否则_1","chinese":"快走，否则我们就迟到了。","pinyin":"Kuài zǒu, fǒuzé wǒmen jiù chídào le.","english":"Hurry up, otherwise we’ll be late.","tags":["generated","hsk4","word-否则"]},
  {"id":"002_否则_2","chinese":"努力一点，否则你会后悔。","pinyin":"Nǔlì yīdiǎn, fǒuzé nǐ huì hòuhuǐ.","english":"Work harder, otherwise you’ll regret it.","tags":["generated","hsk4","word-否则"]},
  {"id":"003_可惜_1","chinese":"今天下雨了，真可惜。","pinyin":"Jīntiān xiàyǔ le, zhēn kěxī.","english":"It’s raining today, what a pity.","tags":["generated","hsk4","word-可惜"]}
]
```

Save this JSON file to your `/input` directory (e.g. `input/hsk4_examples.json`) and the script will automatically process it.

---

## Input JSON Format

Each input file must contain a list of sentence objects:

```
{
  "id": "058_稍微_3",
  "chinese": "这个菜稍微加点盐会更好吃。",
  "pinyin": "Zhège cài shāowēi jiā diǎn yán huì gèng hǎochī.",
  "english": "This dish would taste better with a little more salt.",
  "tags": ["generated","hsk4","word-稍微"]
}
```

---

## Usage

1. Make sure Anki is running with **AnkiConnect** enabled.  
2. Place your generated JSON files in the `/input` directory.  
3. Run the script:

```
python3 anki_tts_uploader.py
```

To preview actions **without uploading** or modifying your files:

```
python3 anki_tts_uploader.py --dry
```

---

## Example Console Output

```
Loaded config: config.yml
Deck: Chinese Sentences  Model: Chinese Model
Input dir: ./input  Dry run: False
Loaded 15 items from 1 files.
[TTS] Using gTTS for item 001_故意_1 ...
[UPLOAD] uploading tts_guyi_4ac2b4a9c7.mp3 to Anki media ...
[OK] Created new card: 001_故意_1 (Note ID: 1683247029333)
[SAVE] updated JSON written to input/hsk4_examples.json
Done.
```

---

## Notes

- Automatically skips items missing `"chinese"`.  
- Falls back to Google Translate TTS if `gTTS` isn’t available.  
- Safe to re-run — existing cards are updated, not duplicated.  
- Creates `.bak.json` backups or `.dryrun.json` preview outputs.

---
