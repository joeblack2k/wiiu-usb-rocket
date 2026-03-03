# CHECK.MD - Agent Implementatie Validatie

**Instructie voor de Agent:**
Lees dit document als de absolute technische waarheid voor dit project. Controleer de bestaande codebase stap voor stap. Controleer of elke onderstaande vereiste, inclusief bestandsextracties, byte-offsets, cryptografische constanten en datatypes, exact is geïmplementeerd. 

Als een onderdeel ontbreekt, incorrect is geïmplementeerd, of afwijkt van deze specificaties: schrijf, refactor of corrigeer de code direct zodat het werkend in het project zit volgens onderstaande eisen. Gebruik Python's `struct` module voor binaire parsing om endianness-fouten te voorkomen.

## 1. Algemene Setup & Requirements
- [ ] De applicatie gebruikt `requests` voor HTTP-verkeer.
- [ ] De applicatie gebruikt `pycryptodome` voor AES-operaties.

## 2. Wii U Common Key Extractie (otp.bin)
- [ ] De code vereist de aanwezigheid van een lokaal `otp.bin` bestand in de map keys van het project  (de OTP backup van de console).
- [ ] De code leest `otp.bin` in als binaire data (`rb`). in de map 'keys' in het project
- [ ] **Wii U Common Key Extractie**: Exact 16 bytes worden gelezen vanaf offset `0xE0`. Dit is de `WII_U_COMMON_KEY` in binaire vorm.

- [ ] Deze geëxtraheerde binaire data wordt in het geheugen opgeslagen voor gebruik in de ticket decryptie.

## 3. Ticket (.tik) Parsing
- [ ] De code leest lokaal verstrekte `.tik` bestanden in als binaire data (`rb`).
- [ ] **Encrypted Title Key**: Exact 16 bytes worden gelezen op offset `0x1BF`.
- [ ] **Title ID**: Exact 8 bytes worden gelezen op offset `0x1DC` (Geparseerd als Big Endian `unsigned long long`, struct format `>Q`).

## 4. Title Key Decryptie
- [ ] De Encrypted Title Key (uit stap 3) wordt gedecrypt via AES-128-CBC.
- [ ] De decryptie-sleutel is de dynamisch geëxtraheerde `WII_U_COMMON_KEY` (uit stap 2).
- [ ] De Initialization Vector (IV) voor deze stap is exact 16 bytes lang: de originele 8-byte Title ID, direct aangevuld met 8 hexadecimale nul-bytes (`\x00\x00\x00\x00\x00\x00\x00\x00`).
- [ ] De resulterende *Decrypted Title Key* wordt in het geheugen opgeslagen.

## 5. Title Metadata (TMD) Download & Parsing
- [ ] De applicatie maakt een HTTP GET-verzoek naar `http://nus.cdn.wup.shop.nintendo.net/ccs/download/{Title_ID}/tmd` en slaat de binaire data op in het geheugen of tijdelijk lokaal.
- [ ] **Content Count**: Er worden 2 bytes gelezen op offset `0x1DE` (Geparseerd als Big Endian `unsigned short`, struct format `>H`).
- [ ] **Content Records Iteratie**: De code start met het lezen van de iteratieve records op offset `0xB04`. Elk record wordt behandeld als exact 36 bytes (`0x24`) lang. De loop draait exact het aantal keren zoals gespecificeerd in *Content Count*.
- [ ] Binnen elk 36-byte record worden de volgende waarden correct geëxtraheerd:
  - [ ] **Content ID**: 4 bytes op record-offset `+0x00` (Big Endian `unsigned int`, struct format `>I`). Deze wordt omgezet naar een hexadecimale string zonder '0x' prefix voor de URL.
  - [ ] **Index**: 2 bytes op record-offset `+0x04` (behouden als ruwe binaire data voor de AES IV in stap 7).
  - [ ] **Size**: 8 bytes op record-offset `+0x08` (Big Endian `unsigned long long`, struct format `>Q`).

## 6. Content (.app) Downloaden
- [ ] Voor elke geëxtraheerde Content ID maakt de applicatie een HTTP GET-verzoek naar `http://nus.cdn.wup.shop.nintendo.net/ccs/download/{Title_ID}/{Content_ID}`.
- [ ] De gedownloade ruwe data wordt lokaal weggeschreven als `{Content_ID}.app`.

## 7. Content (.app) Decryptie
- [ ] Elk versleuteld `{Content_ID}.app` bestand wordt ingelezen en in blokken gedecrypt via AES-128-CBC.
- [ ] De decryptie-sleutel is de *Decrypted Title Key* (uit stap 4).
- [ ] De Initialization Vector (IV) voor deze specifieke content is exact 16 bytes lang: de ruwe 2-byte **Index** van die specifieke content (uit stap 5), direct aangevuld met 14 hexadecimale nul-bytes.
- [ ] De gedecrypteerde data wordt correct en verifieerbaar weggeschreven ter vervanging van, of naast, de versleutelde bestanden.
