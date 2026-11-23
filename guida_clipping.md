# Guida rapida: da video YouTube a clip verticali sottotitolate

Flusso: **scarico il video → scrivo `clips.txt` → lancio `clipper.py` → trovo le clip in `clips_out/`**

---

## 1. Setup (si fa UNA volta sola)

```bash
brew install ffmpeg yt-dlp python@3.12
python3.12 -m venv ~/.venv
source ~/.venv/bin/activate
pip install --upgrade pip
pip install faster-whisper pillow
```

Controllo: `python --version` deve dire **3.12.x** (con Python più recenti faster-whisper non si installa).

---

## 2. Ogni volta che apri un nuovo terminale

```bash
source ~/.venv/bin/activate
cd ~/Desktop/clypper
```

Se vedi `(.venv)` all'inizio del prompt, l'ambiente è attivo.
La cartella `clypper` deve contenere: `clipper.py`, `clips.txt` e il video.

---

## 3. Scaricare il video da YouTube

```bash
yt-dlp -f "bv*+ba/b" --merge-output-format mp4 "https://www.youtube.com/watch?v=XXXXXXXXXXX"
```

- Il file viene salvato nella cartella in cui ti trovi (controlla con `pwd`, aprila con `open .`).
- Per scegliere la cartella: aggiungi `-P ~/Desktop/clypper`
- Rinomina il file in qualcosa di semplice:
  ```bash
  mv *XXXXXXXXXXX*.mp4 ep28.mp4
  ```
  (al posto di `XXXXXXXXXXX` metti l'ID del video, la parte dopo `v=`)

**Scaricare solo i sottotitoli automatici** (utile per cercare i momenti salienti):

```bash
yt-dlp --write-auto-subs --sub-langs "it" --convert-subs srt --skip-download "URL"
```

**Se yt-dlp dà errore** ("Sign in to confirm you're not a bot" o simili):
- aggiornalo: `brew upgrade yt-dlp`
- oppure aggiungi `--cookies-from-browser chrome` (o `safari`, `firefox`)

---

## 4. Sintassi di `clips.txt`

Una clip per riga:

```
inizio-fine | titolo
```

Esempio:

```
# Falsissimo EP. 28
00:00:54-00:01:45 | I gay e la normalita
01:21:50-01:22:40 | Hai mai ucciso qualcuno
1:26:45-1:27:20 | Pagellone Express
12:30-13:20 | Clip da 12 minuti e 30
45-95 | Clip dal secondo 45 al 95
```

**Regole**

| Cosa | Dettaglio |
|---|---|
| Separatore tempi | trattino `-` tra inizio e fine |
| Separatore titolo | barra verticale `\|` (il titolo è opzionale) |
| Formati tempo accettati | `SS`, `MM:SS`, `H:MM:SS`, anche con decimali (`12:30.5`) |
| Commenti | righe che iniziano con `#` |
| Righe vuote | ignorate |
| Durata massima | oltre 60s ti avvisa, ma la clip viene fatta lo stesso |
| Nome file di output | `NN_titolo-in-minuscolo.mp4`, dove NN segue l'ordine delle righe |
| Riga sbagliata | viene saltata con un avviso `[!] riga N ignorata` |

Il titolo serve solo per il nome del file, non compare nel video.

---

## 5. Generare le clip

```bash
python clipper.py ep28.mp4 clips.txt
```

Le clip vengono salvate in `clips_out/`. Per aprirla: `open clips_out`.
La prima volta scarica il modello Whisper (circa 500 MB).
Se rilanci, le clip con lo stesso nome vengono sovrascritte.

**Opzioni**

| Opzione | Cosa fa |
|---|---|
| `--mode blur` | (default) video intero al centro con sfondo sfocato, ideale per due persone ai lati |
| `--mode crop` | ritaglio centrale a tutto schermo |
| `--model base` | trascrizione veloce ma meno precisa (per i test) |
| `--model small` | (default) buon compromesso |
| `--model medium` | più preciso con nomi propri, più lento |
| `--model large-v3` | massima precisione, molto lento |
| `--words 2` | meno parole per riga di sottotitolo (default 3) |
| `--font /percorso/font.ttf` | font personalizzato per i sottotitoli |
| `--lang it` | lingua del parlato (default `it`) |
| `--no-subs` | solo taglio e formato 9:16, senza sottotitoli |
| `-o nome_cartella` | cartella di output diversa da `clips_out` |

Esempio completo:

```bash
python clipper.py ep28.mp4 clips.txt --mode crop --model medium --words 2 -o clip_ep28
```

---

## 6. Problemi già incontrati e soluzioni

| Errore | Causa | Soluzione |
|---|---|---|
| `pkg-config is required for building PyAV` | Python troppo recente | usare Python 3.12 (punto 1) |
| `open() got an unexpected keyword argument 'metadata_errors'` | `av` troppo nuovo per faster-whisper | già risolto in `clipper.py` (legge l'audio da solo) |
| `No option name near 'sub.ass'` | ffmpeg di Homebrew senza libass | già risolto: i sottotitoli ora usano Pillow |
| `Manca Pillow` | libreria non installata | `pip install pillow` |
| Avviso `HF_TOKEN` / "unauthenticated requests" | normale, non è un errore | ignorare |
| `command not found: python` | ambiente non attivo | `source ~/.venv/bin/activate` |

---

## 7. Dopo le clip

Lo script fa taglio, formato 9:16 e sottotitoli parola per parola (parola pronunciata in giallo).
Zoom, effetti sonori, pop-up con foto e split-screen vanno aggiunti a mano in CapCut importando le clip da `clips_out`.
Controlla sempre i sottotitoli prima di pubblicare: Whisper può sbagliare nomi propri e parole poco comuni.
