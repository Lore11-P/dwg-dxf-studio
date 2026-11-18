# DWG / DXF Studio

App desktop (Windows) per aprire disegni **DWG/DXF**, modificarli e convertirli in **PDF**, **PNG**
o **JPG**. Anteprima nella finestra, scelta della tavola (Model o layout di carta), formato pagina
e risoluzione.

## Installazione rapida (da GitHub)

Incolla nel terminale (PowerShell o Prompt dei comandi) questi comandi:

```
git clone https://github.com/Lore11-P/dwg-dxf-studio.git
cd dwg-dxf-studio
installa.bat
```

`installa.bat` fa tutto: crea `.venv`, installa le dipendenze, crea la scorciatoia sul desktop
e avvia l'app. Va eseguito una volta sola.
Per aggiornare: `git pull` e di nuovo `installa.bat`.

In una riga sola, da PowerShell (installa in `%USERPROFILE%\dwg-dxf-studio` e avvia):

```
git clone https://github.com/Lore11-P/dwg-dxf-studio.git "$env:USERPROFILE\dwg-dxf-studio"; & "$env:USERPROFILE\dwg-dxf-studio\installa.bat"
```

Serve **Windows 10/11** e **Python 3.10 o successivo** (provato con 3.14). Se manca Python,
l'installer te lo dice con il link per scaricarlo. Per leggere e scrivere i **DWG** serve anche
**ODA File Converter** (gratuito): vedi più sotto.

## Installazione a mano

Scarica la cartella con **Code → Download ZIP** oppure `git clone`, poi nella cartella dell'app:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Le dipendenze sono ezdxf, PyMuPDF e Pillow. Se la cartella contiene già `.venv`, questo passo
non serve.

## Avvio

Doppio clic su **`Avvia app.bat`** (apre la finestra senza console).
In alternativa:

```
.venv\Scripts\python.exe app.py
```

Puoi anche passare subito un file: `"Avvia app.bat" "C:\disegni\pianta.dxf"`.

## Scorciatoia sul desktop

Esegui una volta **`Crea scorciatoia desktop.bat`**: crea sul desktop la voce
**DWG-DXF Studio** che avvia l'app con doppio clic (funziona anche se sposti la cartella,
perché punta al percorso assoluto attuale; se sposti l'app, riesegui lo script).

In alternativa, creala a mano: tasto destro sul desktop → **Nuovo → Scorciatoia** → sfoglia
fino a `Avvia app.bat` → nome "DWG-DXF Studio".

## Uso

1. **Apri DWG/DXF…** e scegli il file (oppure avvia l'app passando il percorso).
2. Scegli la **tavola** da esportare, il **formato** pagina (A4…A0, oppure "Adatta al disegno")
   e la **risoluzione** delle immagini.
3. **Esporta PDF / PNG / JPG**: il file viene salvato dove indichi, con il nome del disegno.

**Monocromatico** converte tutto in nero: utile per stampe e PDF da ufficio.
Il PDF è vettoriale; il testo è convertito in contorni, quindi non è selezionabile.

Nell'elenco delle tavole non compaiono i layout di carta vuoti (quelli che contengono solo la
finestra del foglio, come i "Layout1" appena creati da AutoCAD). Un layout con una finestra che
non inquadra nulla viene esportato come pagina bianca, senza errori.

## Modifica del disegno

Il pannello di destra modifica il disegno aperto, non solo l'esportazione.

- **Click sull'anteprima** per selezionare un'entità: il riquadro arancione la evidenzia e il
  pannello mostra layer, colore, spessore e (per i testi) il contenuto. A parità di click vince
  l'entità più piccola, così un testo sopra una polilinea si seleziona dal testo.
- **Proprietà**: layer, colore (tavolozza o "Da layer"), spessore di linea, testo di TEXT/MTEXT.
- **Trasforma**: sposta di ΔX/ΔY, ruota di un angolo, scala di un fattore; oppure trascina
  l'entità selezionata con il mouse. **Snap** arrotonda lo spostamento al passo scelto.
  Rotazione e scala avvengono attorno al centro dell'entità.
- **Elimina** (o tasto Canc) e **Ctrl+Z** per annullare tutto, comprese le modifiche ai layer.
  La cronologia è in memoria e si azzera cambiando tavola.
- **Layer**: elenco con `[x]`/`[ ]` per accendere e spegnere, e colore del layer.
- **Salva DXF…** / **Salva DWG…**: scrive una copia modificata. Il DWG richiede ODA File
  Converter (lo stesso usato per aprirli). Il file originale non viene mai sovrascritto da solo.

Le modifiche sono visualizzate dopo il rendering dell'anteprima: su disegni molto grandi
(decine di migliaia di entità) l'aggiornamento richiede alcuni secondi.

## File DWG

Su questo PC **ODA File Converter 27.10 è già installato**
(`C:\Program Files\ODA\ODAFileConverter 27.10.0`), quindi i DWG si aprono direttamente.
L'app lo trova anche quando il programma è installato in una cartella con il numero di versione.

Su un altro PC va installato una volta: <https://www.opendesign.com/guestfiles/oda_file_converter>
(versione Windows 64 bit, gratuito per uso non commerciale). Se manca, l'app lo segnala con il link.
I **DXF** invece si aprono sempre, senza installare nulla.

## Prove

```
.venv\Scripts\python.exe app.py --selftest
```

Genera un DXF di prova, lo riapre con la stessa catena usata dall'app e verifica
esportazione PDF/PNG/JPG, monocromatica, selezione, trasformazioni, undo e salvataggio delle
modifiche. `esempio.dxf` è una planimetria dimostrativa generata da `crea_esempio.py`;
`esempio.dwg` è la stessa planimetria in DWG, usata per provare l'apertura dei DWG.

Per provare una cartella intera di file veri:

```
.venv\Scripts\python.exe prova_cartella.py "C:\cartella" "C:\uscita"
```

Esporta ogni tavola di ogni DWG/DXF della cartella in PNG e PDF, stampando tempi ed errori
(senza aprire la finestra).

## Limiti noti

- Un disegno alla volta; niente drag & drop.
- Si modifica un'entità per volta (niente selezione multipla).
- Il click sceglie l'entità dal suo riquadro, non dal contorno esatto: su disegni con molti
  riquadri sovrapposti conviene ingrandire (l'app non ha zoom).
- Si modificano le entità della tavola: l'istanza di un blocco sì, la definizione condivisa no.
  Gli attributi interni ai blocchi e il contenuto visto attraverso le finestre di layout non
  sono selezionabili.
- Tabelle (ACAD_TABLE), multileader e oggetti OLE si vedono ma non si possono selezionare né modificare.
- Layout di carta multipli: si esportano uno per volta scegliendoli nell'elenco.
- Disegni molto densi (es. 36 000 entità) richiedono ~30 s per il rendering: la finestra resta
  utilizzabile e mostra "Rendering…", ma l'esportazione va attesa. Durante la scrittura di un
  file (un attimo in DXF, qualche secondo in DWG) non conviene modificare il disegno.
- Con "Adatta al disegno" le immagini vengono limitate a 6000 px sul lato lungo.
